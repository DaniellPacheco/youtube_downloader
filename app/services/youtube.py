from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from yt_dlp import YoutubeDL

from app.utils import canonical_url, extract_video_id


def _metadata(info: dict[str, Any]) -> dict[str, Any]:
    if info.get("_type") == "playlist" or info.get("entries"):
        raise ValueError("Playlists não são suportadas no MVP.")
    if info.get("is_live") or info.get("live_status") == "is_live":
        raise ValueError("Transmissões ao vivo em andamento não são suportadas.")
    duration = info.get("duration")
    if not duration:
        raise ValueError("Não foi possível determinar a duração do vídeo.")
    heights = sorted({int(f["height"]) for f in info.get("formats", []) if f.get("vcodec") != "none" and f.get("height")})
    return {
        "id": info["id"], "url": canonical_url(info["id"]), "title": info.get("title") or "Vídeo",
        "duration": float(duration), "thumbnail": info.get("thumbnail"), "resolutions": heights,
    }


def analyze(url: str) -> dict[str, Any]:
    video_id = extract_video_id(url)
    with YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}) as ydl:
        return _metadata(ydl.extract_info(canonical_url(video_id), download=False))


def download_source(url: str, output_stem: Path, resolution: int | None, progress: Callable[[float, str], None]) -> Path:
    selector = "bestvideo*+bestaudio/best"
    if resolution:
        selector = f"bestvideo*[height<={resolution}]+bestaudio/best[height<={resolution}]"

    def hook(data: dict[str, Any]) -> None:
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            pct = (data.get("downloaded_bytes", 0) / total * 100) if total else 0
            progress(min(pct, 99), "Baixando vídeo e áudio")

    options = {
        "format": selector, "outtmpl": str(output_stem) + ".%(ext)s", "merge_output_format": "mp4",
        "noplaylist": True, "progress_hooks": [hook], "quiet": True, "no_warnings": True,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        candidate = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    if candidate.exists():
        return candidate
    matches = list(output_stem.parent.glob(output_stem.name + ".*"))
    if not matches:
        raise RuntimeError("O download terminou sem produzir um arquivo.")
    return matches[0]

