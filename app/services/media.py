from __future__ import annotations

import json
import shutil
import subprocess
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[float], None]


def dependency_status() -> dict[str, bool]:
    return {name: shutil.which(name) is not None for name in ("ffmpeg", "ffprobe")}


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "h264_nvenc" in result.stdout


def video_encoder() -> str:
    return "h264_nvenc" if nvenc_available() else "libx264"


def encoder_label(encoder: str | None = None) -> str:
    return "NVIDIA NVENC" if (encoder or video_encoder()) == "h264_nvenc" else "CPU"


def _codec_args(encoder: str) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(detail[-1][:500] if detail else "FFmpeg falhou.")


def _run_with_progress(args: list[str], expected_duration: float, progress: ProgressCallback | None = None) -> None:
    command = [*args[:-1], "-progress", "pipe:1", "-nostats", args[-1]]
    tail: deque[str] = deque(maxlen=20)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1,
    )
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if line:
            tail.append(line)
        if progress and line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                elapsed = int(line.split("=", 1)[1]) / 1_000_000
                progress(min(99.0, max(0.0, elapsed / expected_duration * 100)))
            except (ValueError, ZeroDivisionError):
                pass
        elif progress and line == "progress=end":
            progress(100.0)
    if process.wait():
        ignored = ("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time", "dup_frames=", "drop_frames=", "speed=", "progress=")
        useful = [line for line in tail if not line.startswith(ignored)]
        raise RuntimeError((useful[-1] if useful else "FFmpeg falhou.")[:500])


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _transcode_video(source: Path, output: Path, expected_duration: float, input_args: list[str] | None = None,
                     output_args: list[str] | None = None, resolution: int | None = None,
                     progress: ProgressCallback | None = None) -> str:
    scale = ["-vf", f"scale=-2:min({resolution}\\,ih)"] if resolution else []
    encoder = video_encoder()
    base = ["ffmpeg", "-y", *(input_args or []), "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", *(output_args or []), *scale]
    suffix = ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    try:
        _run_with_progress([*base, *_codec_args(encoder), *suffix], expected_duration, progress)
        return encoder
    except RuntimeError:
        if encoder != "h264_nvenc":
            raise
        output.unlink(missing_ok=True)
        if progress:
            progress(0.0)
        _run_with_progress([*base, *_codec_args("libx264"), *suffix], expected_duration, progress)
        return "libx264"


def normalize_mp4(source: Path, output: Path, resolution: int | None = None,
                  progress: ProgressCallback | None = None, expected_duration: float | None = None) -> str:
    if resolution:
        return _transcode_video(source, output, expected_duration or duration(source), resolution=resolution, progress=progress)
    copy_args = ["ffmpeg", "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", str(output)]
    try:
        _run(copy_args)
        if progress:
            progress(100.0)
        return "copy"
    except RuntimeError:
        output.unlink(missing_ok=True)
        return _transcode_video(source, output, expected_duration or duration(source), progress=progress)


def precise_clip(source: Path, output: Path, start: float, end: float, resolution: int | None = None,
                 progress: ProgressCallback | None = None) -> str:
    clip_duration = end - start
    return _transcode_video(
        source, output, clip_duration,
        input_args=["-ss", f"{start:.3f}"],
        output_args=["-t", f"{clip_duration:.3f}"],
        resolution=resolution,
        progress=progress,
    )


def extract_audio(source: Path, output: Path, audio_format: str, progress: ProgressCallback | None = None,
                  expected_duration: float | None = None, start: float | None = None,
                  end: float | None = None) -> None:
    if (start is None) != (end is None) or (start is not None and (start < 0 or start >= end)):
        raise ValueError("Informe início e fim válidos para o corte de áudio.")
    if audio_format == "mp3":
        codecs = ["-c:a", "libmp3lame", "-q:a", "2"]
    else:
        codecs = ["-c:a", "aac", "-b:a", "192k"]
    seek = ["-ss", f"{start:.3f}"] if start is not None else []
    trim = ["-t", f"{end - start:.3f}"] if start is not None else []
    total = end - start if start is not None else expected_duration or duration(source)
    _run_with_progress(["ffmpeg", "-y", *seek, "-i", str(source), *trim, "-vn", *codecs, str(output)],
                       total, progress)
