from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from app.config import Settings
from app.db import Database, now
from app.services import audio_ai, media, youtube
from app.utils import canonical_url, safe_filename


class JobWorker:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await asyncio.to_thread(self.process, job_id)
            finally:
                self.queue.task_done()

    def update(self, job_id: str, status: str, progress: float, message: str) -> None:
        self.db.execute("UPDATE jobs SET status=?, progress=?, message=?, updated_at=? WHERE id=?", (status, round(progress, 1), message, now(), job_id))

    def process(self, job_id: str) -> None:
        work = self.settings.temp_dir / job_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
            source = self.db.one("SELECT * FROM sources WHERE id=?", (job["source_id"],)) if job else None
            if not job or not source:
                raise RuntimeError("Tarefa ou fonte não encontrada.")
            self.update(job_id, "analyzing", 2, "Preparando processamento")
            source_path = Path(source["path"]) if source.get("path") else None
            if not source_path or not source_path.exists():
                usage = shutil.disk_usage(self.settings.base_dir)
                if usage.free < self.settings.min_free_bytes:
                    raise RuntimeError("Espaço livre insuficiente para iniciar o download.")
                self.update(job_id, "downloading", 5, "Iniciando download")
                downloaded = youtube.download_source(
                    canonical_url(source["id"]), work / "source", None,
                    lambda pct, msg: self.update(job_id, "downloading", 5 + pct * .65, msg),
                )
                source_path = self.settings.sources_dir / f"{source['id']}.mp4"
                media.normalize_mp4(downloaded, source_path)
                self.db.execute("UPDATE sources SET path=?, status='ready' WHERE id=?", (str(source_path), source["id"]))
            self.update(job_id, "processing", 75, "Gerando arquivo final")
            def media_progress(percent: float) -> None:
                label = media.encoder_label() if job["kind"] != "audio" else "FFmpeg"
                self.update(job_id, "processing", 75 + min(percent, 100) * .24, f"Processando com {label}")

            result_id = uuid.uuid4().hex
            base = safe_filename(source["title"])
            if job["kind"] == "audio":
                ext = job["audio_format"]
                suffix = "audio-corte" if job["start_time"] is not None else "audio"
                if job["remove_music"] or job["reduce_noise"]:
                    suffix += "-tratado"
                filename = f"{base}-{suffix}.{ext}"
                mime = "audio/mp4" if ext == "m4a" else "audio/mpeg"
                output = self.settings.results_dir / f"{result_id}.{ext}"
                if job["remove_music"] or job["reduce_noise"]:
                    audio_ai.clean_audio(
                        source_path, output, ext, work / "ai", self.settings.base_dir / "models",
                        bool(job["remove_music"]), bool(job["reduce_noise"]), float(source["duration"]),
                        start=job["start_time"], end=job["end_time"],
                        status=lambda pct, message: self.update(job_id, "processing", 75 + pct * .24, message),
                    )
                else:
                    media.extract_audio(source_path, output, ext, media_progress, float(source["duration"]),
                                        start=job["start_time"], end=job["end_time"])
            else:
                suffix = "corte" if job["kind"] == "clip" else "video"
                filename, mime = f"{base}-{suffix}.mp4", "video/mp4"
                output = self.settings.results_dir / f"{result_id}.mp4"
                if job["kind"] == "clip":
                    media.precise_clip(source_path, output, job["start_time"], job["end_time"], job.get("resolution"), media_progress)
                else:
                    media.normalize_mp4(source_path, output, job.get("resolution"), media_progress, float(source["duration"]))
            created = now()
            self.db.execute(
                "INSERT INTO results(id,source_id,job_id,kind,filename,path,mime_type,size,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (result_id, source["id"], job_id, job["kind"], filename, str(output), mime, output.stat().st_size, created),
            )
            self.db.execute("UPDATE jobs SET status='completed',progress=100,message='Concluído',result_id=?,updated_at=? WHERE id=?", (result_id, created, job_id))
        except Exception as exc:
            self.db.execute("UPDATE jobs SET status='failed',error_code='processing_failed',error_detail=?,message='Falha no processamento',updated_at=? WHERE id=?", (str(exc)[:1000], now(), job_id))
        finally:
            shutil.rmtree(work, ignore_errors=True)
