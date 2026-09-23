from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class ValidationError(ValueError):
    pass


def extract_video_id(value: str) -> str:
    value = value.strip()
    if VIDEO_ID_RE.fullmatch(value):
        return value
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise ValidationError("URL inválida.") from exc
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise ValidationError("Informe uma URL de vídeo do YouTube.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if parse_qs(parsed.query).get("list"):
            raise ValidationError("Playlists não são suportadas no MVP.")
    elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
        parts = parsed.path.strip("/").split("/")
        video_id = parts[1] if len(parts) > 1 else ""
    else:
        raise ValidationError("A URL precisa apontar para um vídeo individual.")
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValidationError("Não foi possível identificar o vídeo.")
    return video_id


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_time(value: str | float | int | None) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = value.strip()
        try:
            parts = [float(part) for part in text.split(":")]
        except ValueError as exc:
            raise ValidationError("Use segundos, MM:SS ou HH:MM:SS.") from exc
        if len(parts) == 1:
            seconds = parts[0]
        elif len(parts) == 2 and 0 <= parts[1] < 60:
            seconds = parts[0] * 60 + parts[1]
        elif len(parts) == 3 and 0 <= parts[1] < 60 and 0 <= parts[2] < 60:
            seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
        else:
            raise ValidationError("Use segundos, MM:SS ou HH:MM:SS.")
    if seconds < 0:
        raise ValidationError("O tempo não pode ser negativo.")
    return seconds


def safe_filename(value: str, fallback: str = "arquivo") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9._ -]+", "", normalized)
    normalized = re.sub(r"[ ._-]+", "-", normalized).strip("-.")
    return normalized[:100] or fallback

