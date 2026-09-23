from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.db import Database, now
from app.worker import JobWorker


def test_worker_completes_video_and_cleans_temp(tmp_path: Path):
    settings = Settings(tmp_path / "data", min_free_bytes=1)
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.initialize()
    created = now()
    db.execute("INSERT INTO sources(id,url,title,duration,status,created_at) VALUES(?,?,?,?,?,?)", ("dQw4w9WgXcQ", "url", "Teste", 30, "metadata", created))
    db.execute("INSERT INTO jobs(id,kind,source_id,status,progress,message,created_at,updated_at) VALUES(?,?,?,'queued',0,'',?,?)", ("job1", "video", "dQw4w9WgXcQ", created, created))

    def fake_download(url, stem, resolution, progress):
        output = stem.with_suffix(".webm")
        output.write_bytes(b"source")
        progress(50, "Baixando")
        return output

    def fake_normalize(source, output, resolution=None, progress=None, expected_duration=None):
        output.write_bytes(b"result")
        if progress:
            progress(50)

    with patch("app.worker.youtube.download_source", side_effect=fake_download), patch("app.worker.media.normalize_mp4", side_effect=fake_normalize):
        JobWorker(db, settings).process("job1")

    job = db.one("SELECT * FROM jobs WHERE id='job1'")
    assert job["status"] == "completed"
    assert job["progress"] == 100
    assert not (settings.temp_dir / "job1").exists()


def test_interrupted_jobs_fail_on_initialize(tmp_path: Path):
    settings = Settings(tmp_path / "data")
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.initialize()
    created = now()
    db.execute("INSERT INTO sources(id,url,title,duration,status,created_at) VALUES(?,?,?,?,?,?)", ("dQw4w9WgXcQ", "url", "Teste", 30, "metadata", created))
    db.execute("INSERT INTO jobs(id,kind,source_id,status,progress,message,created_at,updated_at) VALUES(?,?,?,'processing',50,'',?,?)", ("job1", "video", "dQw4w9WgXcQ", created, created))
    db.initialize()
    assert db.one("SELECT status FROM jobs WHERE id='job1'")["status"] == "failed"
