import pytest

from app.utils import ValidationError, extract_video_id, parse_time, safe_filename


@pytest.mark.parametrize("value", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtube.com/shorts/dQw4w9WgXcQ",
    "dQw4w9WgXcQ",
])
def test_extract_video_id(value):
    assert extract_video_id(value) == "dQw4w9WgXcQ"


@pytest.mark.parametrize("value", [
    "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/channel/example",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123",
])
def test_rejects_unsupported_urls(value):
    with pytest.raises(ValidationError):
        extract_video_id(value)


@pytest.mark.parametrize(("value", "expected"), [("90", 90), ("01:30", 90), ("1:02:03.5", 3723.5), (12, 12)])
def test_parse_time(value, expected):
    assert parse_time(value) == expected


@pytest.mark.parametrize("value", ["-1", "1:99", "1:02:99", "abc"])
def test_invalid_time(value):
    with pytest.raises(ValidationError):
        parse_time(value)


def test_safe_filename():
    assert safe_filename("  Vídeo: teste? / ótimo  ") == "Video-teste-otimo"

