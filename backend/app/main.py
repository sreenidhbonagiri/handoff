import logging
import shutil
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, llm, photos, pipeline, report, state
from .config import FFMPEG, FRONTEND_DIST, MODEL, WHISPER_CLI, WHISPER_MODEL
from .schemas import FactReviewIn, HandoffNoteIn, Health, JobListItem, JobState, ObservationIn, SourceEditIn
from .transcribe import router as transcribe_router
from .transcribe import sweep_orphans

log = logging.getLogger("uvicorn.error")
get_conn = db.get_conn


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    conn = db.connect()
    try:
        removed = sweep_orphans(conn)
    finally:
        conn.close()
    if removed:
        log.info("Removed %d abandoned recording(s): %s", len(removed), ", ".join(removed))
    yield


app = FastAPI(title="Handoff", version="0.1.0", lifespan=lifespan)
app.include_router(transcribe_router)


def _state_or_error(fn, *args) -> JobState:
    try:
        return fn(*args)
    except pipeline.JobNotFound:
        raise HTTPException(404, "not found")
    except llm.LLMError as e:
        raise HTTPException(503, f"Local model unavailable or returned unusable output: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))


class JobCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    location: str | None = Field(default=None, max_length=200)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)


@app.get("/api/health", response_model=Health)
def health() -> Health:
    info = llm.model_info()
    return Health(
        model=MODEL,
        ffmpeg_available=shutil.which(FFMPEG) is not None,
        whisper_available=shutil.which(WHISPER_CLI) is not None and WHISPER_MODEL.exists(),
        whisper_model=WHISPER_MODEL.name,
        **info,
    )


@app.get("/api/jobs", response_model=list[JobListItem])
def list_jobs(conn: sqlite3.Connection = Depends(get_conn)) -> list[JobListItem]:
    return [JobListItem(job=job, facts=db.list_facts(conn, job.id)) for job in db.list_jobs(conn)]


@app.post("/api/jobs", response_model=JobState)
def create_job(body: JobCreate, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    job_id = db.create_job(conn, body.title, body.location)
    return pipeline.build_state(conn, job_id)


@app.get("/api/jobs/{job_id}", response_model=JobState)
def get_job(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    return _state_or_error(pipeline.build_state, conn, job_id)


@app.patch("/api/jobs/{job_id}", response_model=JobState)
def update_job(job_id: int, body: JobUpdate, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    if body.title is None and body.location is None:
        raise HTTPException(400, "title or location is required")
    if db.update_job(conn, job_id, title=body.title, location=body.location) is None:
        raise HTTPException(404, "not found")
    return _state_or_error(pipeline.build_state, conn, job_id)


@app.post("/api/jobs/{job_id}/observations", response_model=JobState)
def add_observation(job_id: int, obs: ObservationIn, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    return _state_or_error(pipeline.add_observation, conn, job_id, obs)


@app.post("/api/jobs/{job_id}/photos", response_model=JobState)
def add_photo(
    job_id: int,
    photo: UploadFile = File(...),
    caption: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
) -> JobState:
    def run() -> JobState:
        name = photos.save_upload(photo)
        try:
            return pipeline.add_observation(
                conn, job_id, ObservationIn(kind="photo", photo_path=name, text=caption or ""),
            )
        except Exception:
            if name not in photos.referenced_photo_names(conn):
                photos.delete_file(name)
            raise

    return _state_or_error(run)


@app.get("/api/jobs/{job_id}/photos/{name}")
def get_photo(job_id: int, name: str, conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    if db.get_job(conn, job_id) is None:
        raise HTTPException(404, "not found")
    try:
        path = photos.photo_path(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not photos.source_owns_photo(conn, job_id, name) or not path.exists():
        raise HTTPException(404, "not found")
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@app.patch("/api/jobs/{job_id}/handoff", response_model=JobState)
def save_handoff_note(job_id: int, body: HandoffNoteIn, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    if db.set_handoff_note(conn, job_id, body.note) is None:
        raise HTTPException(404, "not found")
    return _state_or_error(pipeline.build_state, conn, job_id)


@app.post("/api/jobs/{job_id}/facts/{fact_id}/confirm", response_model=JobState)
def confirm_fact(job_id: int, fact_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    def run() -> JobState:
        state.confirm_fact(conn, job_id, fact_id)
        conn.commit()
        return pipeline.build_state(conn, job_id)

    return _state_or_error(run)


@app.post("/api/jobs/{job_id}/facts/{fact_id}/review", response_model=JobState)
def review_fact(job_id: int, fact_id: int, body: FactReviewIn, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    def run() -> JobState:
        state.review_fact(conn, job_id, fact_id, body.value, body.state)
        conn.commit()
        return pipeline.build_state(conn, job_id)

    return _state_or_error(run)


@app.patch("/api/sources/{source_id}", response_model=JobState)
def edit_source(source_id: int, body: SourceEditIn, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    return _state_or_error(pipeline.edit_source, conn, source_id, body.text)


@app.post("/api/sources/{source_id}/extract", response_model=JobState)
def retry_source(source_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> JobState:
    return _state_or_error(pipeline.retry_source, conn, source_id)


def _report_opts(mode: str, note: str | None) -> tuple[str, str | None]:
    if mode not in ("completed", "handoff"):
        raise HTTPException(400, "mode must be completed or handoff")
    return mode, note


@app.get("/api/jobs/{job_id}/report.html", response_class=HTMLResponse)
def report_html(
    job_id: int,
    mode: str = Query("completed"),
    note: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> HTMLResponse:
    kind, handoff_note = _report_opts(mode, note)
    st = _state_or_error(pipeline.build_state, conn, job_id)
    return HTMLResponse(report.render_html(st, mode=kind, handoff_note=handoff_note))


@app.get("/api/jobs/{job_id}/report.json")
def report_json(
    job_id: int,
    mode: str = Query("completed"),
    note: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> JSONResponse:
    kind, handoff_note = _report_opts(mode, note)
    st = _state_or_error(pipeline.build_state, conn, job_id)
    return JSONResponse(report.build_json(st, mode=kind, handoff_note=handoff_note))


def _spa_index() -> FileResponse:
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        raise HTTPException(404, "not found")
    return FileResponse(index)


@app.get("/jobs")
@app.get("/jobs/")
def spa_jobs() -> FileResponse:
    return _spa_index()


@app.get("/jobs/{job_id}")
def spa_job(job_id: int) -> FileResponse:
    return _spa_index()


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
