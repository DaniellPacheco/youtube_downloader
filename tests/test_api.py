from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient

from app.main import create_app


INFO = {
    "id": "dQw4w9WgXcQ",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "title": "Vídeo de teste",
    "duration": 120.0,
    "thumbnail": "https://example.test/thumb.jpg",
    "resolutions": [360, 720, 1080],
}


def client(tmp_path: Path):
    return TestClient(create_app(tmp_path / "data"))


def test_analyze_and_create_job(tmp_path):
    with patch("app.main.youtube.analyze", return_value=INFO), client(tmp_path) as api:
        analyzed = api.post("/api/analyze", json={"url": INFO["url"]})
        assert analyzed.status_code == 200
        assert analyzed.json()["resolutions"] == [360, 720, 1080]

        created = api.post("/api/jobs", json={"kind": "clip", "source_id": INFO["id"], "start": "00:10", "end": "00:20", "resolution": 720})
        assert created.status_code == 202
        job = api.get(f"/api/jobs/{created.json()['id']}")
        assert job.status_code == 200
        assert job.json()["kind"] == "clip"


def test_clip_validation(tmp_path):
    with patch("app.main.youtube.analyze", return_value=INFO), client(tmp_path) as api:
        api.post("/api/analyze", json={"url": INFO["url"]})
        reversed_times = api.post("/api/jobs", json={"kind": "clip", "source_id": INFO["id"], "start": "1:00", "end": "0:30"})
        assert reversed_times.status_code == 422
        too_long = api.post("/api/jobs", json={"kind": "clip", "source_id": INFO["id"], "start": "1:00", "end": "3:00"})
        assert too_long.status_code == 422


def test_library_and_delete_source(tmp_path):
    with patch("app.main.youtube.analyze", return_value=INFO), client(tmp_path) as api:
        api.post("/api/analyze", json={"url": INFO["url"]})
        library = api.get("/api/library")
        assert library.status_code == 200
        assert library.json()["sources"][0]["id"] == INFO["id"]
        deleted = api.delete(f"/api/sources/{INFO['id']}")
        assert deleted.status_code == 204


def test_health_shape(tmp_path):
    with client(tmp_path) as api:
        response = api.get("/api/health")
        assert response.status_code == 200
        assert set(response.json()["dependencies"]) == {"ffmpeg", "ffprobe"}


def test_ai_requires_optional_dependencies(tmp_path):
    with patch("app.services.audio_ai.available", return_value=False), client(tmp_path) as api:
        response = api.post("/api/jobs", json={"kind": "audio", "source_id": INFO["id"], "remove_music": True})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "ai_not_installed"


@pytest.mark.parametrize("options", [{}, {"remove_music": True}, {"reduce_noise": True}, {"remove_music": True, "reduce_noise": True}])
def test_audio_ai_options_persist_and_default_off(tmp_path, options):
    with patch("app.services.audio_ai.available", return_value=True), patch("app.main.youtube.analyze", return_value=INFO), patch("app.worker.JobWorker.start"), client(tmp_path) as api:
        api.post("/api/analyze", json={"url": INFO["url"]})
        response = api.post("/api/jobs", json={"kind": "audio", "source_id": INFO["id"], **options})
        assert response.status_code == 202
        job = api.get(f"/api/jobs/{response.json()['id']}").json()
        assert bool(job["remove_music"]) == options.get("remove_music", False)
        assert bool(job["reduce_noise"]) == options.get("reduce_noise", False)


def test_video_rejects_audio_ai_options(tmp_path):
    with client(tmp_path) as api:
        response = api.post("/api/jobs", json={"kind": "video", "source_id": INFO["id"], "reduce_noise": True})
        assert response.status_code == 422


@pytest.mark.parametrize("times", [
    {"start": "1:00", "end": "0:30"},
    {"start": "1:00", "end": "3:00"},
    {"start": "0:10"},
    {"end": "0:20"},
    {"start": "", "end": ""},
    {"start": -1, "end": 20},
])
def test_audio_clip_rejects_invalid_range(tmp_path, times):
    with patch("app.main.youtube.analyze", return_value=INFO), client(tmp_path) as api:
        api.post("/api/analyze", json={"url": INFO["url"]})
        response = api.post("/api/jobs", json={"kind": "audio", "source_id": INFO["id"], **times})
        assert response.status_code == 422


@pytest.mark.parametrize("audio_format", ["m4a", "mp3"])
@pytest.mark.parametrize("times", [{}, {"start": "00:10", "end": "00:20"}])
def test_audio_job_accepts_full_audio_and_clip(tmp_path, audio_format, times):
    with patch("app.main.youtube.analyze", return_value=INFO), patch("app.worker.JobWorker.start"), client(tmp_path) as api:
        api.post("/api/analyze", json={"url": INFO["url"]})
        response = api.post("/api/jobs", json={"kind": "audio", "source_id": INFO["id"], "audio_format": audio_format, **times})
        assert response.status_code == 202
        job = api.get(f"/api/jobs/{response.json()['id']}").json()
        assert job["start_time"] == (10 if times else None)
        assert job["end_time"] == (20 if times else None)
        assert job["audio_format"] == audio_format

