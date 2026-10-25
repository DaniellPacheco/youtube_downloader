import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.db import Database
from app.services import audio_ai


def fake_torch(cuda=False, mps=False):
    return SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda, device_count=lambda: 2,
                             get_device_properties=lambda i: SimpleNamespace(total_memory=(i + 1) * 4096),
                             set_device=MagicMock(), get_device_name=lambda i: f"GPU {i}", empty_cache=MagicMock()),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)), device=lambda name: name,
    )


def test_gpu_has_priority_and_selects_largest_card():
    torch = fake_torch(cuda=True, mps=True)
    label, directml = audio_ai.select_accelerator(torch)
    assert label == "GPU: GPU 1" and not directml
    torch.cuda.set_device.assert_called_once_with(1)


def test_cpu_without_accelerator():
    with patch("app.services.audio_ai.importlib.util.find_spec", return_value=None):
        assert audio_ai.select_accelerator(fake_torch())[0].startswith("CPU")


def test_directml_is_automatically_enabled():
    directml = SimpleNamespace(is_available=lambda: True)
    with patch("app.services.audio_ai.importlib.util.find_spec", return_value=object()), patch.dict(sys.modules, torch_directml=directml):
        assert audio_ai.select_accelerator(fake_torch()) == ("GPU DirectML", True)


@pytest.mark.parametrize("music,noise", [(True, False), (False, True), (True, True)])
def test_cleaning_pipeline_trims_before_ai_and_encodes_once(tmp_path, music, noise):
    torch = fake_torch()
    separator_module = SimpleNamespace(Separator=object())
    work = tmp_path / "work"
    sources = []
    models = []

    def separate(source, stage_dir, model_dir, model, stem, *args):
        sources.append(source)
        models.append((model, stem))
        result = stage_dir / "clean.wav"
        result.write_bytes(b"audio")
        return result

    with patch.dict(sys.modules, {"torch": torch, "audio_separator": SimpleNamespace(), "audio_separator.separator": separator_module}), patch(
        "app.services.audio_ai.select_accelerator", return_value=("CPU", False)
    ), patch("app.services.audio_ai.media._run_with_progress") as prepare, patch(
        "app.services.audio_ai._separate", side_effect=separate
    ), patch("app.services.audio_ai.media.extract_audio") as encode:
        audio_ai.clean_audio(tmp_path / "source.mp4", tmp_path / "out.mp3", "mp3", work, tmp_path / "models",
                             music, noise, 120, start=10, end=25)
    command, total, _ = prepare.call_args.args
    assert command[command.index("-ss") + 1] == "10.000"
    assert command[command.index("-t") + 1] == "15.000"
    assert total == 15
    assert sources[0] == work / "input.wav"
    expected = ([(audio_ai.MUSIC_MODEL, "Vocals")] if music else []) + ([(audio_ai.NOISE_MODEL, "No Noise")] if noise else [])
    assert models == expected
    if music and noise:
        assert sources[1] == work / "stage-0" / "clean.wav"
    assert encode.call_count == 1
    assert encode.call_args.args[0] == work / f"stage-{len(expected) - 1}" / "clean.wav"
    assert encode.call_args.args[-1] == 15


def test_gpu_failure_retries_on_cpu(tmp_path):
    calls = []

    class Separator:
        def __init__(self, **kwargs):
            self.torch_device = "cuda"

        def load_model(self, **kwargs):
            calls.append(self.torch_device)
            if self.torch_device == "cuda":
                raise RuntimeError("CUDA out of memory")

        def separate(self, source):
            result = tmp_path / "clean.wav"
            result.write_bytes(b"audio")
            return ["clean.wav"]

    messages = []
    result = audio_ai._separate(tmp_path / "input.wav", tmp_path, tmp_path, "model.pth", "Vocals",
                                fake_torch(cuda=True), Separator, "GPU NVIDIA", False, messages.append)
    assert calls == ["cuda", "cpu"]
    assert result == tmp_path / "clean.wav"
    assert any("tentando novamente na CPU" in message for message in messages)


def test_model_download_error_does_not_retry_as_cpu(tmp_path):
    separator = MagicMock()
    separator.return_value.load_model.side_effect = RuntimeError("Download failed")
    with pytest.raises(RuntimeError, match="Download failed"):
        audio_ai._separate(tmp_path / "in.wav", tmp_path, tmp_path, "model.pth", "Vocals",
                           fake_torch(cuda=True), separator, "GPU NVIDIA", False, lambda _: None)
    assert separator.call_count == 1


def test_existing_database_migrates_without_losing_jobs(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY, status TEXT, error_code TEXT, error_detail TEXT, updated_at TEXT)")
        db.execute("INSERT INTO jobs(id,status) VALUES('old','completed')")
    database = Database(path)
    database.initialize()
    database.initialize()
    job = database.one("SELECT * FROM jobs WHERE id='old'")
    assert job["status"] == "completed"
    assert job["remove_music"] == job["reduce_noise"] == 0
