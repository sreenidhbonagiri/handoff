"""observe -> interpret (local model) -> check (validator) -> evaluate checklist -> ask."""

import sqlite3

from . import checklist, db, llm, mapping, photos, state
from .config import MODEL
from .schemas import JobState, ObservationIn, Source
from .transcribe import recording_path


class JobNotFound(LookupError):
    pass


def build_state(conn: sqlite3.Connection, job_id: int) -> JobState:
    job = db.get_job(conn, job_id)
    if job is None:
        raise JobNotFound(job_id)
    facts = db.list_facts(conn, job_id)
    active = [f for f in facts if f.active]
    statuses, question, readiness = checklist.evaluate(active)
    run = db.last_run(conn, job_id)
    return JobState(
        job=job,
        procedure_title=checklist.load_checklist()["title"],
        sources=db.list_sources(conn, job_id),
        facts=facts,
        checklist=statuses,
        next_question=question,
        readiness=readiness,
        last_run=run[0] if run else None,
        rejected=run[1] if run else [],
    )


def job_context(conn: sqlite3.Connection, job_id: int) -> str:
    """Checklist status and the tests this job already knows about, for the model's context."""
    rows = db.active_fact_rows(conn, job_id)
    statuses, _, _ = checklist.evaluate([f for f in db.list_facts(conn, job_id) if f.active])
    lines = ["Checklist:"] + [f"- {s.id} {s.label}: {s.status.replace('_', ' ')}" for s in statuses]
    tests = [mapping.FINAL_TEST_NAME + " (checklist R3)"] + mapping.other_tests_in_job(rows)
    lines.append("Tests in this job: " + "; ".join(tests))
    return "\n".join(lines)


def run_extraction(conn: sqlite3.Connection, job_id: int, source: Source, question: str | None = None) -> None:
    active = [dict(r) for r in db.active_fact_rows(conn, job_id)]
    context = job_context(conn, job_id)
    if source.kind == "photo":
        context += (
            "\nThe technician note is a caption they typed for a photo. "
            "Extract only what the caption states. The photo itself was not analyzed."
        )
    try:
        result = llm.extract(source.text, active, question, context)
    except llm.LLMError as e:
        db.insert_run(conn, job_id, source.id, MODEL, ok=False, error=str(e))
        conn.commit()
        raise
    rejected = state.apply_extraction(conn, job_id, source, result.items)
    db.insert_run(conn, job_id, source.id, MODEL, ok=True, metrics=result.metrics, raw_output=result.raw, rejected=rejected)
    conn.commit()


def _question_for(conn: sqlite3.Connection, job_id: int, requirement_id: str | None) -> str | None:
    if not requirement_id:
        return None
    current = build_state(conn, job_id)
    if current.next_question and current.next_question.requirement_id == requirement_id:
        return current.next_question.text
    req = next((r for r in current.checklist if r.id == requirement_id), None)
    return req.label if req else None


def add_observation(conn: sqlite3.Connection, job_id: int, obs: ObservationIn) -> JobState:
    if db.get_job(conn, job_id) is None:
        raise JobNotFound(job_id)
    audio_path = None
    if obs.audio_path:
        path = recording_path(obs.audio_path)
        if not path.exists():
            raise ValueError("The recording for this transcript is no longer available. Record it again.")
        audio_path = str(path)
    photo_name = None
    if obs.photo_path:
        path = photos.photo_path(obs.photo_path)
        if not path.exists():
            raise ValueError("The photo is no longer available. Add it again.")
        photo_name = path.name
    question = _question_for(conn, job_id, obs.answers_requirement)
    source = db.insert_source(
        conn, job_id, obs.kind, obs.text.strip(),
        audio_path=audio_path, photo_path=photo_name, segments=obs.segments,
        answers_requirement=obs.answers_requirement,
        original_transcript=obs.original_transcript, transcription_ms=obs.transcription_ms,
    )
    conn.commit()
    if source.kind == "photo" and not source.text:
        return build_state(conn, job_id)
    run_extraction(conn, job_id, source, question)
    return build_state(conn, job_id)


def retry_source(conn: sqlite3.Connection, source_id: int) -> JobState:
    source = db.get_source(conn, source_id)
    if source is None:
        raise JobNotFound(source_id)
    if source.kind == "photo" and not source.text.strip():
        raise ValueError("This photo has no caption to extract. Add a caption first.")
    state.invalidate_source(conn, source.job_id, source.id)
    run_extraction(conn, source.job_id, source, _question_for(conn, source.job_id, source.answers_requirement))
    return build_state(conn, source.job_id)


def edit_source(conn: sqlite3.Connection, source_id: int, text: str) -> JobState:
    """Sources are immutable: an edit creates a revised source and re-interprets it."""
    old = db.get_source(conn, source_id)
    if old is None or old.replaced_by is not None:
        raise JobNotFound(source_id)
    if old.kind != "photo" and not text.strip():
        raise ValueError("text must not be blank")
    new = db.insert_source(
        conn, old.job_id, old.kind, text,
        audio_path=old.audio_path, photo_path=old.photo_path, segments=old.segments,
        answers_requirement=old.answers_requirement,
        revises=old.id, original_transcript=old.original_transcript, transcription_ms=old.transcription_ms,
    )
    db.mark_source_replaced(conn, old.id, new.id)
    state.invalidate_source(conn, old.job_id, old.id)
    conn.commit()
    if new.kind == "photo" and not new.text.strip():
        return build_state(conn, old.job_id)
    run_extraction(conn, old.job_id, new, _question_for(conn, old.job_id, old.answers_requirement))
    return build_state(conn, old.job_id)
