from __future__ import annotations

import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_settings
from app.db import Database, now
from app.schemas import AnalyzeRequest, JobRequest
from app.services import media, youtube
from app.utils import ValidationError, canonical_url, extract_video_id, parse_time
from app.worker import JobWorker

ACTIVE = ("queued", "analyzing", "downloading", "processing")


def create_app(data_dir: Path | None = None) -> FastAPI:
    settings = load_settings() if data_dir is None else load_settings().__class__(data_dir.resolve())
    settings.ensure_dirs()
    db = Database(settings.db_path)
    worker = JobWorker(db, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.initialize()
        shutil.rmtree(settings.temp_dir, ignore_errors=True)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        worker.start()
        yield
        await worker.stop()

    app = FastAPI(title="Downloader de YouTube", version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.worker, app.state.settings = db, worker, settings

    @app.exception_handler(ValidationError)
    async def validation_handler(_: Request, exc: ValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_input", "message": str(exc)}})

    @app.get("/api/health")
    def health():
        deps = media.dependency_status()
        return {"ok": all(deps.values()), "dependencies": deps}

    @app.post("/api/analyze")
    def analyze(payload: AnalyzeRequest):
        try:
            info = youtube.analyze(payload.url)
        except ValidationError:
            raise
        except Exception as exc:
            raise HTTPException(422, detail={"code": "analysis_failed", "message": str(exc)[:500]}) from exc
        db.execute(
            "INSERT INTO sources(id,url,title,duration,thumbnail,status,created_at) VALUES(?,?,?,?,?,'metadata',?) "
            "ON CONFLICT(id) DO UPDATE SET url=excluded.url,title=excluded.title,duration=excluded.duration,thumbnail=excluded.thumbnail",
            (info["id"], info["url"], info["title"], info["duration"], info["thumbnail"], now()),
        )
        return info

    @app.post("/api/jobs", status_code=202)
    def create_job(payload: JobRequest):
        if payload.source_id:
            source = db.one("SELECT * FROM sources WHERE id=?", (payload.source_id,))
            if not source:
                raise HTTPException(404, detail={"code": "source_not_found", "message": "Fonte não encontrada."})
        else:
            video_id = extract_video_id(payload.url or "")
            source = db.one("SELECT * FROM sources WHERE id=?", (video_id,))
            if not source:
                try:
                    info = youtube.analyze(canonical_url(video_id))
                except Exception as exc:
                    raise HTTPException(422, detail={"code": "analysis_failed", "message": str(exc)[:500]}) from exc
                db.execute("INSERT INTO sources(id,url,title,duration,thumbnail,status,created_at) VALUES(?,?,?,?,?,'metadata',?)", (info["id"], info["url"], info["title"], info["duration"], info["thumbnail"], now()))
                source = db.one("SELECT * FROM sources WHERE id=?", (video_id,))
        start, end = parse_time(payload.start), parse_time(payload.end)
        if payload.kind == "clip":
            if start is None or end is None or start >= end:
                raise ValidationError("O fim precisa ser maior que o início.")
            if end > float(source["duration"]):
                raise ValidationError("O fim ultrapassa a duração do vídeo.")
        job_id, created = uuid.uuid4().hex, now()
        db.execute(
            "INSERT INTO jobs(id,kind,source_id,status,progress,message,resolution,start_time,end_time,audio_format,created_at,updated_at) VALUES(?,?,?,'queued',0,'Na fila',?,?,?,?,?,?)",
            (job_id, payload.kind, source["id"], payload.resolution, start, end, payload.audio_format, created, created),
        )
        worker.queue.put_nowait(job_id)
        return {"id": job_id, "status": "queued"}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job:
            raise HTTPException(404, detail={"code": "job_not_found", "message": "Tarefa não encontrada."})
        if job.get("result_id"):
            job["download_url"] = f"/api/files/{job['result_id']}"
        return job

    @app.get("/api/library")
    def library():
        sources = db.all("SELECT * FROM sources ORDER BY created_at DESC")
        results = db.all("SELECT id,source_id,kind,filename,mime_type,size,created_at FROM results ORDER BY created_at DESC")
        return {"sources": sources, "results": results}

    @app.get("/api/files/{result_id}")
    def download(result_id: str):
        result = db.one("SELECT * FROM results WHERE id=?", (result_id,))
        if not result or not Path(result["path"]).is_file():
            raise HTTPException(404, detail={"code": "file_not_found", "message": "Arquivo não encontrado."})
        return FileResponse(result["path"], media_type=result["mime_type"], filename=result["filename"])

    @app.delete("/api/files/{result_id}", status_code=204)
    def delete_result(result_id: str):
        result = db.one("SELECT * FROM results WHERE id=?", (result_id,))
        if not result:
            raise HTTPException(404, detail={"code": "file_not_found", "message": "Arquivo não encontrado."})
        Path(result["path"]).unlink(missing_ok=True)
        db.execute("UPDATE jobs SET result_id=NULL WHERE result_id=?", (result_id,))
        db.execute("DELETE FROM results WHERE id=?", (result_id,))

    @app.delete("/api/sources/{source_id}", status_code=204)
    def delete_source(source_id: str):
        source = db.one("SELECT * FROM sources WHERE id=?", (source_id,))
        if not source:
            raise HTTPException(404, detail={"code": "source_not_found", "message": "Fonte não encontrada."})
        placeholders = ",".join("?" for _ in ACTIVE)
        active = db.one(f"SELECT id FROM jobs WHERE source_id=? AND status IN ({placeholders}) LIMIT 1", (source_id, *ACTIVE))
        if active:
            raise HTTPException(409, detail={"code": "source_busy", "message": "A fonte está sendo usada por uma tarefa."})
        if db.one("SELECT id FROM results WHERE source_id=? LIMIT 1", (source_id,)):
            raise HTTPException(409, detail={"code": "source_has_results", "message": "Exclua primeiro os resultados desta fonte."})
        if source.get("path"):
            Path(source["path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM jobs WHERE source_id=?", (source_id,))
        db.execute("DELETE FROM sources WHERE id=?", (source_id,))

    static = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


app = create_app()
