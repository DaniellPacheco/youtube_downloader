"""Opt-in smoke test: downloads models and runs real local inference.

Set YTD_RUN_AI_TESTS=1 and ensure FFmpeg/FFprobe are on PATH.
"""
import math
import os
import struct
import wave

import pytest

from app.services import audio_ai, media


@pytest.mark.skipif(os.getenv("YTD_RUN_AI_TESTS") != "1", reason="IA real exige dependências e download de modelos")
@pytest.mark.parametrize("music,noise,extension", [(True, False, "m4a"), (False, True, "mp3"), (True, True, "m4a")])
def test_real_audio_cleanup(tmp_path, music, noise, extension):
    source = tmp_path / "input.wav"
    rate = 44100
    with wave.open(str(source), "wb") as wav:
        wav.setparams((2, 2, rate, 0, "NONE", "not compressed"))
        frames = bytearray()
        for index in range(rate * 6):
            sample = int(5000 * math.sin(2 * math.pi * 220 * index / rate)
                         + 1500 * math.sin(2 * math.pi * 1300 * index / rate))
            frames.extend(struct.pack("<hh", sample, sample))
        wav.writeframes(frames)
    result = tmp_path / f"result.{extension}"
    messages = []
    # Reuse the application's persistent model cache across test runs.
    from app.config import load_settings

    audio_ai.clean_audio(source, result, extension, tmp_path / "work", load_settings().base_dir / "models",
                         music, noise, 6, start=1, end=4,
                         status=lambda pct, text: messages.append((pct, text)))
    assert result.stat().st_size > 100
    assert media.duration(result) == pytest.approx(3, abs=.2)
    assert messages[-1][0] == 100
    print(messages)
