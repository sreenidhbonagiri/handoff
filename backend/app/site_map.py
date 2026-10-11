"""Local floor-plan storage and pin-status derivation. The image is never sent to the model."""

import re
import sqlite3
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from . import checklist, config, db, photos
from .schemas import Fact, MapJobItem, PinStatus, RequirementStatus, SiteMapState, SitePlan

MAX_PLAN_BYTES = 8 * 1024 * 1024
MAX_PLAN_PIXELS = 20_000_000
_PLAN_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png)$")
PENDING = frozenset({"needs_review", "conflicting"})
OPEN_CHECK = frozenset({"not_recorded", "planned", "not_complete"})


def site_dir() -> Path:
    return config.SITE_DIR


def plan_path(name_or_path: str) -> Path:
    name = Path(name_or_path).name
    if not _PLAN_NAME.match(name):
        raise ValueError("not a stored floor plan")
    path = (site_dir() / name).resolve()
    if path.parent != site_dir().resolve():
        raise ValueError("floor plan is outside the site folder")
    return path


def validate_coords(x: float, y: float) -> tuple[float, float]:
    try:
        xf, yf = float(x), float(y)
    except (TypeError, ValueError) as e:
        raise ValueError("Pin coordinates must be numbers between 0 and 1.") from e
    if not (0.0 <= xf <= 1.0 and 0.0 <= yf <= 1.0):
        raise ValueError("Pin coordinates must be between 0 and 1.")
    if xf != xf or yf != yf:  # NaN
        raise ValueError("Pin coordinates must be between 0 and 1.")
    return xf, yf


def pending_facts(facts: list[Fact]) -> list[Fact]:
    return [f for f in facts if f.active and f.review_status in PENDING]


def unresolved_issues(facts: list[Fact]) -> list[Fact]:
    return [f for f in facts if f.active and f.field == "issue" and f.state == "unresolved"]


def open_checks(statuses: list[RequirementStatus]) -> list[RequirementStatus]:
    return [r for r in statuses if r.status in OPEN_CHECK]


def pin_status(facts: list[Fact], statuses: list[RequirementStatus]) -> PinStatus:
    if unresolved_issues(facts):
        return "open_problem"
    if pending_facts(facts) or open_checks(statuses):
        return "needs_attention"
    return "no_open_items"


def save_plan_upload(upload: UploadFile) -> tuple[str, int, int]:
    data = upload.file.read(MAX_PLAN_BYTES + 1)
    if not data:
        raise HTTPException(422, "The floor plan is empty.")
    if len(data) > MAX_PLAN_BYTES:
        raise HTTPException(413, "The floor plan is too large (limit 8 MB).")
    try:
        kind, (width, height) = photos.inspect_image(data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if width * height > MAX_PLAN_PIXELS:
        raise HTTPException(422, "The floor plan is too large in pixels (limit 20 megapixels).")
    folder = site_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{kind}"
    (folder / name).write_bytes(data)
    return name, width, height


def delete_plan_file(name: str) -> None:
    try:
        plan_path(name).unlink(missing_ok=True)
    except ValueError:
        return


def replace_plan(conn: sqlite3.Connection, upload: UploadFile, name: str | None, confirm_replace: bool) -> SitePlan:
    existing = db.get_site_plan(conn)
    pins = db.pin_count(conn)
    if existing and pins and not confirm_replace:
        raise HTTPException(
            409,
            "This floor plan already has job pins. Replacing it will clear those positions. "
            "Confirm to continue.",
        )
    stored, width, height = save_plan_upload(upload)
    try:
        plan = db.set_site_plan(conn, name.strip() if name and name.strip() else None, stored, width, height)
    except Exception:
        delete_plan_file(stored)
        raise
    if existing:
        delete_plan_file(existing.image_name)
    return plan


def map_job_item(conn: sqlite3.Connection, job) -> MapJobItem:
    facts = db.list_facts(conn, job.id)
    pin = db.get_pin(conn, job.id)
    try:
        statuses, _, _ = checklist.evaluate([f for f in facts if f.active])
        return MapJobItem(
            job=job,
            facts=facts,
            checklist=statuses,
            pin=pin,
            status=pin_status(facts, statuses),
            status_error=None,
        )
    except Exception:
        return MapJobItem(
            job=job,
            facts=facts,
            checklist=None,
            pin=pin,
            status=None,
            status_error="Status unavailable.",
        )


def load_state(conn: sqlite3.Connection) -> SiteMapState:
    return SiteMapState(
        plan=db.get_site_plan(conn),
        jobs=[map_job_item(conn, job) for job in db.list_jobs(conn)],
    )
