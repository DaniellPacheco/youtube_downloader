import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import media


def local_client(tmp_path):
    return TestClient(create_app(tmp_path / "data"))


def upload(api, filename="mensagem.opus", content=b"audio"):
    return api.post("/api/sources/upload", files={"file": (filename, content, "application/octet-stream")})


def test_import_reuse_and_delete_preserves_original(tmp_path):
    original = tmp_path / "mensagem.opus"
    original.write_bytes(b"original")
    with patch("app.main.media.dependency_status", return_value={"ffprobe": True, "ffmpeg": True}), patch(
        "app.main.media.audio_metadata", return_value={"duration": 20}
    ), patch("app.worker.JobWorker.start"), local_client(tmp_path) as api:
        response = upload(api, "../../mensagem.opus", original.read_bytes())
        assert response.status_code == 201
        info = response.json()
        assert info["source_type"] == "local" and info["title"] == "mensagem"
        source = api.get("/api/library").json()["sources"][0]
        stored = Path(source["path"])
        assert stored.parent == tmp_path / "data" / "sources"
        assert stored.read_bytes() == original.read_bytes()
        created = api.post("/api/jobs", json={"kind": "audio", "source_id": info["id"], "audio_format": "mp3"})
        assert created.status_code == 202
        job = api.get(f"/api/jobs/{created.json()['id']}").json()
        assert not job["remove_music"] and not job["reduce_noise"]
        # Remove the queued job to allow deletion of the stored copy.
        api.app.state.db.execute("DELETE FROM jobs WHERE id=?", (created.json()["id"],))
        assert api.delete(f"/api/sources/{info['id']}").status_code == 204
        assert not stored.exists()
        assert original.read_bytes() == b"original"


@pytest.mark.parametrize("filename,content,code", [("bad.exe", b"data", 422), ("empty.wav", b"", 422), ("large.wav", b"12345", 413)])
def test_invalid_upload_does_not_leave_files_or_sources(tmp_path, monkeypatch, filename, content, code):
    monkeypatch.setenv("YTD_MAX_UPLOAD_BYTES", "4")
    with patch("app.main.media.dependency_status", return_value={"ffprobe": True}), local_client(tmp_path) as api:
        assert upload(api, filename, content).status_code == code
        assert not api.get("/api/library").json()["sources"]
        assert not list((tmp_path / "data" / "sources").iterdir())


def test_corrupt_media_does_not_leave_files(tmp_path):
    with patch("app.main.media.dependency_status", return_value={"ffprobe": True}), patch(
        "app.main.media.audio_metadata", side_effect=ValueError("Arquivo sem áudio.")
    ), local_client(tmp_path) as api:
        assert upload(api).status_code == 422
        assert not list((tmp_path / "data" / "sources").iterdir())


def test_local_source_never_falls_back_to_youtube(tmp_path):
    with patch("app.main.media.dependency_status", return_value={"ffprobe": True}), patch(
        "app.main.media.audio_metadata", return_value={"duration": 20}
    ), patch("app.worker.JobWorker.start"), patch("app.worker.youtube.download_source") as download, local_client(tmp_path) as api:
        info = upload(api).json()
        assert api.post("/api/jobs", json={"kind": "video", "source_id": info["id"]}).status_code == 422
        job = api.post("/api/jobs", json={"kind": "audio", "source_id": info["id"], "audio_format": "mp3"}).json()
        source = api.get("/api/library").json()["sources"][0]
        Path(source["path"]).unlink()
        assert api.post("/api/jobs", json={"kind": "audio", "source_id": info["id"]}).status_code == 404
        api.app.state.worker.process(job["id"])
        result = api.get(f"/api/jobs/{job['id']}").json()
        assert result["status"] == "failed"
        assert "Arquivo local" in result["error_detail"]
        download.assert_not_called()


@pytest.mark.skipif(not all(media.dependency_status().values()), reason="FFmpeg/FFprobe necessários")
@pytest.mark.parametrize("extension,codec", [("opus", "libopus"), ("ogg", "libopus"), ("m4a", "aac"), ("wav", "pcm_s16le"), ("mp4", "aac")])
def test_real_local_file_to_mp3(tmp_path, extension, codec):
    source = tmp_path / f"input.{extension}"
    args = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    if extension == "mp4":
        args += ["-f", "lavfi", "-i", "color=c=black:s=160x120:d=2", "-c:v", "mpeg4", "-shortest"]
    subprocess.run([*args, "-c:a", codec, str(source)], check=True, capture_output=True, timeout=30)
    with patch("app.worker.JobWorker.start"), patch("app.worker.youtube.download_source") as download, local_client(tmp_path) as api:
        imported = upload(api, source.name, source.read_bytes())
        assert imported.status_code == 201, imported.text
        response = api.post("/api/jobs", json={"kind": "audio", "source_id": imported.json()["id"], "audio_format": "mp3", "start": .25, "end": 1.25})
        assert response.status_code == 202, response.text
        api.app.state.worker.process(response.json()["id"])
        job = api.get(f"/api/jobs/{response.json()['id']}").json()
        assert job["status"] == "completed", job
        result = api.get(job["download_url"])
        assert result.status_code == 200 and result.headers["content-type"] == "audio/mpeg"
        converted = tmp_path / "result.mp3"
        converted.write_bytes(result.content)
        assert media.duration(converted) == pytest.approx(1, abs=.2)
        assert source.is_file()
        download.assert_not_called()
