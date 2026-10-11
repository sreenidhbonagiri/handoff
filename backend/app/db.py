import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH
from .schemas import Fact, Job, Rejection, RunInfo, Segment, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    handoff_note TEXT,
    location TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    audio_path TEXT,
    segments_json TEXT,
    answers_requirement TEXT,
    revises INTEGER REFERENCES sources(id),
    replaced_by INTEGER REFERENCES sources(id),
    original_transcript TEXT,
    transcription_ms REAL
);
CREATE TABLE IF NOT EXISTS fact_revisions (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    field TEXT NOT NULL,
    item TEXT,
    item_key TEXT NOT NULL,
    value TEXT,
    state TEXT NOT NULL,
    quote TEXT NOT NULL,
    quote_start INTEGER NOT NULL,
    quote_end INTEGER NOT NULL,
    corrected_from TEXT,
    supersedes INTEGER REFERENCES fact_revisions(id),
    superseded_by INTEGER REFERENCES fact_revisions(id),
    review_status TEXT NOT NULL DEFAULT 'accepted',
    conflict_group INTEGER,
    invalidated INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    model TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    wall_ms REAL,
    total_ms REAL,
    load_ms REAL,
    prompt_tokens INTEGER,
    eval_tokens INTEGER,
    eval_ms REAL,
    raw_output TEXT,
    rejected_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_job ON fact_revisions(job_id);
CREATE INDEX IF NOT EXISTS idx_sources_job ON sources(job_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Columns added after the first schema; applied to existing databases on connect.
_MIGRATIONS = {
    "jobs": {"handoff_note": "TEXT", "location": "TEXT", "updated_at": "TEXT"},
    "sources": {"original_transcript": "TEXT", "transcription_ms": "REAL", "photo_path": "TEXT"},
}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    for table, columns in _MIGRATIONS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    _backfill_updated_at(conn)
    conn.commit()
    return conn


def _backfill_updated_at(conn: sqlite3.Connection) -> None:
    """Fill updated_at on older rows from the latest saved activity, without changing IDs."""
    conn.execute(
        """
        UPDATE jobs
        SET updated_at = COALESCE((
            SELECT MAX(ts) FROM (
                SELECT created_at AS ts FROM jobs AS j2 WHERE j2.id = jobs.id
                UNION ALL
                SELECT created_at FROM sources WHERE job_id = jobs.id
                UNION ALL
                SELECT created_at FROM fact_revisions WHERE job_id = jobs.id
                UNION ALL
                SELECT created_at FROM runs WHERE job_id = jobs.id
            )
        ), created_at)
        WHERE updated_at IS NULL
        """
    )


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def referenced_audio_names(conn: sqlite3.Connection) -> set[str]:
    """File names of recordings attached to any submitted source (these must be kept)."""
    rows = conn.execute("SELECT DISTINCT audio_path FROM sources WHERE audio_path IS NOT NULL").fetchall()
    return {Path(r[0]).name for r in rows}


def create_job(conn: sqlite3.Connection, title: str = "", location: str | None = None) -> int:
    ts = now()
    loc = location.strip() if location and location.strip() else None
    cur = conn.execute(
        "INSERT INTO jobs (title, location, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (title.strip(), loc, ts, ts),
    )
    conn.commit()
    return cur.lastrowid


def list_jobs(conn: sqlite3.Connection) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY COALESCE(updated_at, created_at) DESC, id DESC"
    ).fetchall()
    return [Job(**dict(r)) for r in rows]


def touch_job(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (now(), job_id))


def update_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    title: str | None = None,
    location: str | None = None,
) -> Job | None:
    if get_job(conn, job_id) is None:
        return None
    if title is not None:
        conn.execute("UPDATE jobs SET title = ? WHERE id = ?", (title.strip(), job_id))
    if location is not None:
        loc = location.strip() or None
        conn.execute("UPDATE jobs SET location = ? WHERE id = ?", (loc, job_id))
    touch_job(conn, job_id)
    conn.commit()
    return get_job(conn, job_id)


def get_job(conn: sqlite3.Connection, job_id: int) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job(**dict(row)) if row else None


def set_handoff_note(conn: sqlite3.Connection, job_id: int, note: str) -> Job | None:
    """Store the technician handoff note on this job only. Does not touch facts."""
    if get_job(conn, job_id) is None:
        return None
    conn.execute("UPDATE jobs SET handoff_note = ? WHERE id = ?", (note, job_id))
    touch_job(conn, job_id)
    conn.commit()
    return get_job(conn, job_id)


def _source(row: sqlite3.Row) -> Source:
    d = dict(row)
    segments = d.pop("segments_json")
    d["segments"] = [Segment(**s) for s in json.loads(segments)] if segments else None
    return Source(**d)


def insert_source(
    conn: sqlite3.Connection,
    job_id: int,
    kind: str,
    text: str,
    audio_path: str | None = None,
    photo_path: str | None = None,
    segments: list[Segment] | None = None,
    answers_requirement: str | None = None,
    revises: int | None = None,
    original_transcript: str | None = None,
    transcription_ms: float | None = None,
) -> Source:
    seg_json = json.dumps([s.model_dump() for s in segments]) if segments else None
    cur = conn.execute(
        """INSERT INTO sources (job_id, kind, text, created_at, audio_path, photo_path, segments_json,
                                answers_requirement, revises, original_transcript, transcription_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, kind, text, now(), audio_path, photo_path, seg_json, answers_requirement, revises,
         original_transcript, transcription_ms),
    )
    touch_job(conn, job_id)
    return get_source(conn, cur.lastrowid)


_SOURCE_SELECT = """
    SELECT s.*, (SELECT r.wall_ms FROM runs r WHERE r.source_id = s.id AND r.ok = 1
                 ORDER BY r.id DESC LIMIT 1) AS extraction_ms
    FROM sources s"""


def get_source(conn: sqlite3.Connection, source_id: int) -> Source | None:
    row = conn.execute(f"{_SOURCE_SELECT} WHERE s.id = ?", (source_id,)).fetchone()
    return _source(row) if row else None


def list_sources(conn: sqlite3.Connection, job_id: int) -> list[Source]:
    rows = conn.execute(f"{_SOURCE_SELECT} WHERE s.job_id = ? ORDER BY s.id", (job_id,)).fetchall()
    return [_source(r) for r in rows]


def mark_source_replaced(conn: sqlite3.Connection, source_id: int, replaced_by: int) -> None:
    conn.execute("UPDATE sources SET replaced_by = ? WHERE id = ?", (replaced_by, source_id))


def _fact(row: sqlite3.Row) -> Fact:
    d = dict(row)
    d.pop("job_id")
    d.pop("item_key")
    d["invalidated"] = bool(d["invalidated"])
    d["active"] = d["superseded_by"] is None and not d["invalidated"]
    return Fact(**d)


def insert_fact(conn: sqlite3.Connection, **cols: Any) -> int:
    cols.setdefault("created_at", now())
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    cur = conn.execute(f"INSERT INTO fact_revisions ({keys}) VALUES ({marks})", tuple(cols.values()))
    return cur.lastrowid


_FACT_UPDATABLE = {"superseded_by", "supersedes", "review_status", "conflict_group", "invalidated", "note"}


def update_fact(conn: sqlite3.Connection, fact_id: int, **cols: Any) -> None:
    if not set(cols) <= _FACT_UPDATABLE:
        raise ValueError(f"cannot update fact columns {set(cols) - _FACT_UPDATABLE}")
    assignments = ", ".join(f"{k} = ?" for k in cols)
    conn.execute(f"UPDATE fact_revisions SET {assignments} WHERE id = ?", (*cols.values(), fact_id))
    row = conn.execute("SELECT job_id FROM fact_revisions WHERE id = ?", (fact_id,)).fetchone()
    if row:
        touch_job(conn, row["job_id"])


def list_facts(conn: sqlite3.Connection, job_id: int) -> list[Fact]:
    rows = conn.execute("SELECT * FROM fact_revisions WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
    return [_fact(r) for r in rows]


def active_fact_rows(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    """Active revisions including the internal item_key used for matching."""
    return conn.execute(
        """SELECT * FROM fact_revisions
           WHERE job_id = ? AND superseded_by IS NULL AND invalidated = 0 ORDER BY id""",
        (job_id,),
    ).fetchall()


def next_conflict_group(conn: sqlite3.Connection, job_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(conflict_group), 0) + 1 FROM fact_revisions WHERE job_id = ?", (job_id,)
    ).fetchone()
    return row[0]


def insert_run(
    conn: sqlite3.Connection,
    job_id: int,
    source_id: int,
    model: str,
    ok: bool,
    error: str | None = None,
    metrics: dict[str, Any] | None = None,
    raw_output: str | None = None,
    rejected: list[Rejection] | None = None,
) -> int:
    m = metrics or {}
    cur = conn.execute(
        """INSERT INTO runs (job_id, source_id, model, ok, error, wall_ms, total_ms, load_ms,
                             prompt_tokens, eval_tokens, eval_ms, raw_output, rejected_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            source_id,
            model,
            int(ok),
            error,
            m.get("wall_ms"),
            m.get("total_ms"),
            m.get("load_ms"),
            m.get("prompt_tokens"),
            m.get("eval_tokens"),
            m.get("eval_ms"),
            raw_output,
            json.dumps([r.model_dump() for r in rejected or []]),
            now(),
        ),
    )
    return cur.lastrowid


def last_run(conn: sqlite3.Connection, job_id: int) -> tuple[RunInfo, list[Rejection]] | None:
    row = conn.execute("SELECT * FROM runs WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    rejected = [Rejection(**r) for r in json.loads(d.pop("rejected_json") or "[]")]
    d.pop("raw_output")
    d.pop("job_id")
    d["ok"] = bool(d["ok"])
    return RunInfo(**d), rejected
