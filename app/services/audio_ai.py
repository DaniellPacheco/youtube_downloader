from __future__ import annotations

import gc
import importlib.util
import logging
from pathlib import Path
from typing import Callable

from app.services import media

INSTALL_MESSAGE = 'IA local não instalada. Instale as dependências opcionais conforme a seção IA local do README e reinicie o aplicativo.'
MUSIC_MODEL = "3_HP-Vocal-UVR.pth"
NOISE_MODEL = "UVR-DeNoise.pth"
StatusCallback = Callable[[float, str], None]


def available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("audio_separator", "torch", "onnxruntime"))


def select_accelerator(torch) -> tuple[str, bool]:
    """Prefer CUDA/ROCm, then MPS or DirectML, with CPU as the last option."""
    if torch.cuda.is_available():
        index = max(range(torch.cuda.device_count()), key=lambda i: torch.cuda.get_device_properties(i).total_memory)
        torch.cuda.set_device(index)
        return f"GPU: {torch.cuda.get_device_name(index)}", False
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "GPU Apple Metal", False
    if importlib.util.find_spec("torch_directml") is not None:
        import torch_directml

        if torch_directml.is_available():
            return "GPU DirectML", True
    return "CPU (GPU compatível indisponível)", False


def _gpu_error(exc: RuntimeError) -> bool:
    detail = str(exc).lower()
    return any(word in detail for word in ("cuda", "cudnn", "out of memory", "directml", "privateuseone", "mps", "hip error"))


def _separate(source: Path, output_dir: Path, model_dir: Path, model: str, stem: str,
              torch, separator_class, label: str, directml: bool, status: Callable[[str], None]) -> Path:
    def run(cpu: bool) -> Path:
        separator = separator_class(
            output_dir=str(output_dir), model_file_dir=str(model_dir), output_format="WAV",
            output_single_stem=stem, use_soundfile=True, use_directml=directml and not cpu,
            log_level=logging.WARNING,
        )
        if cpu:
            separator.torch_device = torch.device("cpu")
            separator.onnx_execution_provider = ["CPUExecutionProvider"]
        status(f"Carregando modelo local em {'CPU' if cpu else label} (primeiro uso pode baixar o modelo)")
        separator.load_model(model_filename=model)
        status(f"Processando IA em {'CPU' if cpu else label}")
        outputs = separator.separate(str(source))
        if len(outputs) != 1:
            raise RuntimeError("A IA não gerou a faixa de áudio esperada.")
        result = Path(outputs[0])
        if not result.is_absolute():
            result = output_dir / result
        if not result.is_file() or result.stat().st_size == 0:
            raise RuntimeError("A IA não gerou um arquivo de áudio válido.")
        return result

    try:
        return run(False)
    except RuntimeError as exc:
        if not label.startswith("GPU") or not _gpu_error(exc):
            raise
        status("GPU indisponível durante o processamento; tentando novamente na CPU")
    # Leave the exception scope before freeing the failed model's GPU allocations.
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return run(True)


def clean_audio(source: Path, output: Path, audio_format: str, work: Path, model_dir: Path,
                remove_music: bool, reduce_noise: bool, expected_duration: float,
                start: float | None = None, end: float | None = None,
                status: StatusCallback | None = None) -> None:
    if not remove_music and not reduce_noise:
        raise ValueError("Selecione ao menos um tratamento de áudio.")
    try:
        import torch
        from audio_separator.separator import Separator
    except (ImportError, OSError) as exc:
        raise RuntimeError(INSTALL_MESSAGE) from exc

    def report(percent: float, message: str) -> None:
        if status:
            status(percent, message)

    label, directml = select_accelerator(torch)
    work.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    total = end - start if start is not None and end is not None else expected_duration
    prepared = work / "input.wav"
    seek = ["-ss", f"{start:.3f}"] if start is not None else []
    trim = ["-t", f"{total:.3f}"] if start is not None else []
    media._run_with_progress(
        ["ffmpeg", "-y", *seek, "-i", str(source), *trim, "-vn", "-ar", "44100", "-ac", "2",
         "-c:a", "pcm_f32le", str(prepared)], total,
        lambda pct: report(pct * .1, "Preparando áudio para IA"),
    )
    stages = []
    if remove_music:
        stages.append((MUSIC_MODEL, "Vocals", "Removendo música"))
    if reduce_noise:
        stages.append((NOISE_MODEL, "No Noise", "Reduzindo ruído"))
    current = prepared
    for index, (model, stem, title) in enumerate(stages):
        stage_dir = work / f"stage-{index}"
        stage_dir.mkdir()
        current = _separate(current, stage_dir, model_dir, model, stem, torch, Separator, label, directml,
                            lambda message, i=index, t=title: report(10 + i * 75 / len(stages), f"{t}: {message}"))
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    media.extract_audio(current, output, audio_format,
                        lambda pct: report(85 + pct * .15, "Convertendo áudio tratado"), total)
