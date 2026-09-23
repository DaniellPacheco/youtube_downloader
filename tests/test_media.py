from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import media


def setup_function():
    media.nvenc_available.cache_clear()


def test_nvenc_detection_when_encoder_is_available():
    result = SimpleNamespace(returncode=0, stdout=" V....D h264_nvenc NVIDIA NVENC H.264 encoder")
    with patch("app.services.media.shutil.which", return_value="ffmpeg.exe"), patch("app.services.media.subprocess.run", return_value=result):
        assert media.nvenc_available() is True
        assert media.video_encoder() == "h264_nvenc"


def test_nvenc_detection_without_ffmpeg():
    with patch("app.services.media.shutil.which", return_value=None):
        assert media.nvenc_available() is False
        assert media.video_encoder() == "libx264"


def test_progress_parser_converts_ffmpeg_microseconds_to_percent():
    fake_process = MagicMock()
    fake_process.stdout = iter(["out_time_us=2500000\n", "progress=continue\n", "out_time_us=5000000\n", "progress=end\n"])
    fake_process.wait.return_value = 0
    values = []
    with patch("app.services.media.subprocess.Popen", return_value=fake_process) as popen:
        media._run_with_progress(["ffmpeg", "-i", "in.mp4", "out.mp4"], 10.0, values.append)
    assert values == [25.0, 50.0, 100.0]
    command = popen.call_args.args[0]
    assert ["-progress", "pipe:1", "-nostats"] == command[-4:-1]


def test_nvenc_failure_falls_back_to_cpu(tmp_path: Path):
    source, output = tmp_path / "source.mp4", tmp_path / "result.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"partial")
    with patch("app.services.media.video_encoder", return_value="h264_nvenc"), patch(
        "app.services.media._run_with_progress", side_effect=[RuntimeError("NVENC error"), None]
    ) as run:
        encoder = media.precise_clip(source, output, 10, 20)
    assert encoder == "libx264"
    assert "h264_nvenc" in run.call_args_list[0].args[0]
    assert "libx264" in run.call_args_list[1].args[0]
    assert run.call_args_list[0].args[0][run.call_args_list[0].args[0].index("-t") + 1] == "10.000"


def test_nvenc_codec_uses_quality_vbr():
    args = media._codec_args("h264_nvenc")
    assert args[args.index("-c:v") + 1] == "h264_nvenc"
    assert args[args.index("-cq") + 1] == "21"
    assert args[args.index("-preset") + 1] == "p5"


def test_cpu_codec_preserves_previous_quality():
    assert media._codec_args("libx264") == ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
