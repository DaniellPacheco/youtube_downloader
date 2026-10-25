from pathlib import Path
from unittest.mock import patch

import pytest

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


@pytest.mark.parametrize("music,noise", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_audio_worker_routes_only_selected_treatments(tmp_path, music, noise):
    settings = Settings(tmp_path / "data")
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.initialize()
    source = settings.sources_dir / "source.mp4"
    source.write_bytes(b"source")
    created = now()
    db.execute("INSERT INTO sources(id,url,title,duration,status,path,created_at) VALUES(?,?,?,?,?,?,?)",
               ("dQw4w9WgXcQ", "url", "Teste", 120, "ready", str(source), created))
    db.execute("INSERT INTO jobs(id,kind,source_id,status,start_time,end_time,audio_format,remove_music,reduce_noise,created_at,updated_at) VALUES(?,?,?,'queued',10,25,'mp3',?,?,?,?)",
               ("audio-job", "audio", "dQw4w9WgXcQ", music, noise, created, created))

    def fake_audio(source, output, *args, **kwargs):
        output.write_bytes(b"result")

    with patch("app.worker.audio_ai.clean_audio", side_effect=fake_audio) as clean, patch(
        "app.worker.media.extract_audio", side_effect=fake_audio
    ) as extract, patch("app.worker.youtube.download_source") as download:
        JobWorker(db, settings).process("audio-job")
    job = db.one("SELECT * FROM jobs WHERE id='audio-job'")
    assert job["status"] == "completed"
    download.assert_not_called()
    if music or noise:
        extract.assert_not_called()
        assert clean.call_args.args[5:7] == (bool(music), bool(noise))
        assert clean.call_args.kwargs["start"] == 10
        assert clean.call_args.kwargs["end"] == 25
    else:
        clean.assert_not_called()
        extract.assert_called_once()
    assert not (settings.temp_dir / "audio-job").exists()
