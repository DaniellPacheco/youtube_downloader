from pathlib import Path
from unittest.mock import patch

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

