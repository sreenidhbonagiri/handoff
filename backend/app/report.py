"""Deterministic report built from active job state. No model-written prose."""

import base64
import re
from datetime import datetime, timezone
from html import escape
from typing import Any

from . import photos
from .photos import CAPTION_NOTE
from .schemas import Fact, JobState, Source

_STATE_LABEL = {
    "reported_complete": "Reported done",
    "planned": "Planned",
    "explicitly_not_complete": "Not done yet",
    "unresolved": "Still open",
    "resolved": "Reported fixed",
    "observed": "Recorded",
}

_REQ_LABEL = {
    "reported": "Recorded",
    "planned": "Planned",
    "not_recorded": "Not recorded",
    "not_complete": "Not done yet",
    "conflicting": "Notes disagree",
    "unresolved": "Still open",
    "not_applicable": "Not needed",
}

_CHECKLIST_TITLE = {
    "R1": "Equipment ID",
    "R2": "Work done and parts used",
    "R3": "Final equipment test",
    "R4": "Problems still open",
    "R5": "Follow-up work",
}

_TARGET_IGNORED = re.compile(r"target_fact_id \d+ ignored \(not an active \w+ fact\)", re.I)
_VALUE_FROM_WORDS = re.compile(r"^value .+ taken from the words after ", re.I)
_REPEAT_VALUE = "the corrected value repeats the value being corrected; confirm the quantity"
PENDING_LABEL = "Please review"


def describe(f: Fact) -> str:
    item = f.item or ""
    if f.field == "asset_id":
        return f"Equipment ID {f.value}"
    if f.field == "part_replaced":
        qty = f"{f.value} \u00d7 " if f.value else "(quantity not recorded) "
        return f"Replace {qty}{item}".strip()
    if f.field == "final_test":
        return "Final equipment test" + (f": {f.value}" if f.value else "")
    if f.field == "issue":
        return f"Problem: {item}"
    if f.field == "follow_up":
        return f"Follow-up: {item or 'recorded'}"
    return item or "Action"


def _fact_json(f: Fact, state: JobState) -> dict[str, Any]:
    src = next((s for s in state.sources if s.id == f.source_id), None)
    return {
        "fact_id": f.id,
        "description": describe(f),
        "field": f.field,
        "item": f.item,
        "value": f.value,
        "state": f.state,
        "review_status": f.review_status,
        "corrected_from": f.corrected_from,
        "evidence": {
            "source_id": f.source_id,
            "source_kind": src.kind if src else None,
            "recorded_at": src.created_at if src else None,
            "quote": f.quote,
            "from_caption": src.kind == "photo" if src else False,
        },
    }


def _sections(state: JobState) -> dict[str, list[Fact]]:
    active = [f for f in state.facts if f.active]
    unsettled = ("conflicting", "needs_review")
    settled = [f for f in active if f.review_status not in unsettled]
    return {
        "asset": [f for f in settled if f.field == "asset_id"],
        "recorded_work": [
            f for f in settled
            if f.state == "reported_complete" and f.field in ("part_replaced", "other_action", "final_test", "follow_up")
        ],
        "planned_or_not_complete": [f for f in settled if f.state in ("planned", "explicitly_not_complete")],
        "unresolved_issues": [f for f in settled if f.field == "issue" and f.state == "unresolved"],
        "resolved_issues": [f for f in settled if f.field == "issue" and f.state == "resolved"],
        "needs_confirmation": [f for f in active if f.review_status in unsettled],
        "superseded": [f for f in state.facts if f.superseded_by is not None and not f.invalidated],
    }


def _superseded_reason(f: Fact, state: JobState) -> str:
    """'corrected' only when the replacing fact records an explicit correction."""
    by = next((x for x in state.facts if x.id == f.superseded_by), None)
    return "corrected" if by is not None and by.corrected_from else "updated"


LOCAL_SAVE = "This report is saved locally on this device. It is not uploaded."
HANDOFF_SUMMARY = "Handoff — work remains. Unresolved issues, missing checks, and pending confirmations are preserved."


def _resolved_note(state: JobState, handoff_note: str | None) -> str | None:
    raw = handoff_note if handoff_note is not None else (state.job.handoff_note or "")
    return raw.strip() or None


def build_json(
    state: JobState,
    *,
    mode: str = "completed",
    handoff_note: str | None = None,
) -> dict[str, Any]:
    sections = _sections(state)
    note = _resolved_note(state, handoff_note)
    return {
        "job": state.job.model_dump(),
        "procedure": state.procedure_title,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report_kind": "handoff" if mode == "handoff" else "completed_work",
        "handoff_note": note,
        "saved_locally": True,
        "readiness": state.readiness.model_dump(),
        "checklist": [r.model_dump() for r in state.checklist],
        "not_recorded": [r.label for r in state.checklist if r.status == "not_recorded"],
        **{name: [_fact_json(f, state) for f in facts] for name, facts in sections.items() if name != "superseded"},
        "superseded": [
            {**_fact_json(f, state), "superseded_by": f.superseded_by, "reason": _superseded_reason(f, state)}
            for f in sections["superseded"]
        ],
        "sources": [
            {
                "source_id": s.id, "kind": s.kind, "recorded_at": s.created_at, "text": s.text,
                "original_transcript": s.original_transcript, "replaced_by": s.replaced_by,
                "photo_id": s.photo_path, "caption": s.text if s.kind == "photo" else None,
            }
            for s in state.sources
        ],
    }


def _test_result(value: str | None) -> str | None:
    v = (value or "").lower()
    if "fail" in v:
        return "Failed"
    if "pass" in v or v == "ok":
        return "Passed"
    return None


def _display_state(f: Fact) -> str:
    if f.review_status == "needs_review":
        return PENDING_LABEL
    if f.review_status == "conflicting":
        return "Notes disagree"
    if f.field == "asset_id":
        return "Recorded"
    if f.field == "final_test" and f.state == "reported_complete":
        return _test_result(f.value) or "Recorded"
    return _STATE_LABEL.get(f.state, f.state)


def _req_badge(c, state: JobState) -> str:
    if c.status == "conflicting":
        held = any(f.review_status == "needs_review" for f in state.facts if f.id in c.fact_ids)
        return PENDING_LABEL if held else "Notes disagree"
    if c.status == "reported" and c.id == "R3":
        test = next((f for f in state.facts if f.active and f.field == "final_test" and f.review_status not in ("needs_review", "conflicting")), None)
        return _test_result(test.value if test else None) or "Recorded"
    if c.status == "reported" and c.id == "R2":
        return "Reported done"
    if c.status == "reported":
        return "Recorded"
    return _REQ_LABEL.get(c.status, c.status.replace("_", " "))


def _checklist_title(c) -> str:
    return _CHECKLIST_TITLE.get(c.id, c.label)


def _checklist_detail(c, state: JobState) -> str:
    pending = c.status == "conflicting"
    if c.id == "R1":
        asset = next((f for f in state.facts if f.active and f.field == "asset_id" and f.review_status not in ("needs_review", "conflicting")), None)
        if asset and asset.value and not pending:
            return f"Equipment ID: {asset.value}"
        return "No equipment ID recorded yet." if not pending else "The equipment ID still needs your review."
    if c.id == "R2":
        if c.status == "reported":
            return "Completed work is recorded."
        if c.status == "planned":
            return "Work is planned. It is not recorded as done."
        if c.status == "not_complete":
            return "Work was reported as not done yet."
        return "No completed work recorded yet." if not pending else "Notes about the work still need your review."
    if c.id == "R3":
        if c.status == "reported":
            test = next((f for f in state.facts if f.active and f.field == "final_test" and f.review_status not in ("needs_review", "conflicting")), None)
            result = _test_result(test.value if test else None)
            if result:
                return f"Final equipment test: {result.lower()}."
            return f"Final equipment test: {test.value}." if test and test.value else "A test result is recorded."
        if c.status == "planned":
            return "The final equipment test is planned. No result is recorded yet."
        if c.status == "not_complete":
            return "The final equipment test was reported as not done yet."
        return "No test result recorded yet." if not pending else "Notes about the final equipment test still need your review."
    if c.id == "R4":
        if c.status == "unresolved":
            names = [f.item for f in state.facts if f.active and f.field == "issue" and f.state == "unresolved" and f.item]
            return f"Still open: {', '.join(names)}." if names else "A problem is still open."
        if c.status == "reported":
            return "No problems are recorded as still open."
        return "No update on remaining problems yet." if not pending else "Notes about remaining problems still need your review."
    if c.id == "R5":
        if c.status == "not_applicable":
            return "No follow-up is needed."
        if c.status == "reported":
            follow = next((f for f in state.facts if f.active and f.field == "follow_up"), None)
            return f"Follow-up: {follow.item or follow.quote}." if follow else "A follow-up plan is recorded."
        return "No follow-up plan recorded yet." if not pending else "Notes about follow-up still need your review."
    return c.detail


def _friendly_notes(note: str | None, review_status: str) -> tuple[list[str], str | None]:
    if not note:
        return [], None
    helpful: list[str] = []
    raw: list[str] = []
    for part in [p.strip() for p in note.split("; ") if p.strip()]:
        if part == CAPTION_NOTE:
            helpful.append(CAPTION_NOTE)
        elif _TARGET_IGNORED.search(part):
            if review_status != "accepted":
                helpful.append("This note could not be matched to an existing item automatically.")
            raw.append(part)
        elif part == _REPEAT_VALUE:
            if review_status != "accepted":
                helpful.append("The quantity in this note is unclear.")
            raw.append(part)
        elif _VALUE_FROM_WORDS.search(part):
            raw.append(part)
        elif part.endswith("?"):
            helpful.append(part)
        elif review_status != "accepted":
            raw.append(part)
    return helpful, "; ".join(raw) if raw else None


def _note_html(f: Fact) -> str:
    helpful, raw = _friendly_notes(f.note, f.review_status)
    parts = [f'<div class="ev">{escape(msg)}</div>' for msg in helpful]
    if raw:
        parts.append(f'<details class="ev"><summary>Technical details</summary>{escape(raw)}</details>')
    return "".join(parts)


def _fact_li(f: Fact) -> str:
    correction = ""
    if f.corrected_from:
        correction = f' <span class="corr">(corrected from \u201c{escape(f.corrected_from)}\u201d)</span>'
    state = _display_state(f)
    proposed = ""
    if f.review_status in ("needs_review", "conflicting"):
        proposed = f'<div class="ev">Proposed change: {escape(_STATE_LABEL.get(f.state, f.state))}</div>'
    origin = f"Source S{f.source_id}"
    if CAPTION_NOTE in (f.note or ""):
        origin = f"Caption on photo S{f.source_id} (not visual analysis)"
    return (
        f"<li><strong>{escape(describe(f))}</strong> \u2014 {escape(state)}{correction}{proposed}"
        f'<div class="ev">{origin}: \u201c{escape(f.quote)}\u201d</div>{_note_html(f)}</li>'
    )


def _section(title: str, facts: list[Fact], empty: str) -> str:
    body = "".join(_fact_li(f) for f in facts) if facts else f'<li class="none">{escape(empty)}</li>'
    return f"<h2>{escape(title)}</h2><ul>{body}</ul>"


def _photo_data_uri(src: Source) -> str | None:
    if not src.photo_path:
        return None
    try:
        path = photos.photo_path(src.photo_path)
    except ValueError:
        return None
    if not path.exists():
        return None
    data = path.read_bytes()
    try:
        kind, _ = photos.inspect_image(data)
    except ValueError:
        return None
    mime = "image/png" if kind == "png" else "image/jpeg"
    return f"data:{mime};base64,{base64.standard_b64encode(data).decode('ascii')}"


def _source_li(src: Source, *, embed_photo: bool = True) -> str:
    cls = ' class="replaced"' if src.replaced_by else ""
    replaced = f" \u2014 replaced by S{src.replaced_by}" if src.replaced_by else ""
    original = ""
    if src.original_transcript and src.original_transcript != src.text:
        original = f'<div class="ev">Original local transcript before review: \u201c{escape(src.original_transcript)}\u201d</div>'
    body = f"<div>{escape(src.text)}</div>" if src.text else ""
    if src.kind == "photo":
        uri = _photo_data_uri(src) if embed_photo else None
        img = f'<img class="photo" src="{uri}" alt="Photo S{src.id}">' if uri else (
            "" if not embed_photo else '<div class="ev">Photo file is missing.</div>'
        )
        caption = (
            f"<div>Caption: {escape(src.text)}</div>"
            if src.text else '<div class="ev">No caption. The photo was not analyzed.</div>'
        )
        body = (
            f"{img}{caption}"
            f'<div class="ev">Photo {escape(src.photo_path or "")} \u2014 stored locally; not interpreted by the model.</div>'
        )
    return (
        f"<li{cls}><strong>S{src.id}</strong> ({escape(src.kind)}, {escape(src.created_at)}){replaced}"
        f"{body}{original}</li>"
    )


def _missing_html(state: JobState, planned: list[Fact]) -> str:
    items: list[str] = []
    for c in state.checklist:
        if c.status == "not_recorded":
            if c.id == "R5":
                items.append("No follow-up recorded in job notes")
            else:
                items.append(f"{_checklist_title(c)} — {_checklist_detail(c, state)}")
        elif c.status in ("planned", "not_complete"):
            items.append(f"{_checklist_title(c)} — {_checklist_detail(c, state)}")
    for f in planned:
        items.append(f"{describe(f)} — {_display_state(f)}")
    # Preserve unique wording while keeping fact-level detail.
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    body = "".join(f"<li>{escape(item)}</li>" for item in unique)
    if not body:
        body = '<li class="none">Every checklist item has some recorded evidence.</li>'
    return f"<h2>Missing information</h2><ul>{body}</ul>"


def _work_facts(s: dict[str, list[Fact]]) -> list[Fact]:
    return [*s["recorded_work"], *s["resolved_issues"]]


def _open_facts(s: dict[str, list[Fact]]) -> list[Fact]:
    return [*s["unresolved_issues"], *s["needs_confirmation"]]


def _asset_html(s: dict[str, list[Fact]]) -> str:
    if not s["asset"]:
        return '<p class="meta">No equipment ID recorded yet.</p>'
    f = s["asset"][0]
    extra = _note_html(f)
    origin = ""
    if CAPTION_NOTE in (f.note or ""):
        origin = (
            f'<p class="ev">Caption on photo S{f.source_id} (not visual analysis): '
            f"\u201c{escape(f.quote)}\u201d</p>"
        )
    elif f.quote:
        origin = f'<p class="ev">Source S{f.source_id}: \u201c{escape(f.quote)}\u201d</p>'
    return f'<p class="meta">{escape(describe(f))}</p>{origin}{extra}'


def _photos_html(state: JobState) -> str:
    photos_src = [src for src in state.sources if src.kind == "photo" and src.replaced_by is None]
    if not photos_src:
        return "<h2>Photos and captions</h2><ul><li class=\"none\">No photos attached.</li></ul>"
    return "<h2>Photos and captions</h2><ul>" + "".join(_source_li(src) for src in photos_src) + "</ul>"


def render_html(
    state: JobState,
    *,
    mode: str = "completed",
    handoff_note: str | None = None,
) -> str:
    s = _sections(state)
    r = state.readiness
    rows = "".join(
        f"<tr><td>{escape(_checklist_title(c))}</td>"
        f'<td class="st {escape(c.status)}">{escape(_req_badge(c, state))}</td>'
        f"<td>{escape(_checklist_detail(c, state))}</td></tr>"
        for c in state.checklist
    )
    sources = "".join(_source_li(src, embed_photo=src.kind != "photo") for src in state.sources)
    superseded = "".join(
        f"<li><s>{escape(describe(f))} \u2014 {escape(_STATE_LABEL.get(f.state, f.state))}</s> "
        f"{_superseded_reason(f, state)} by a later note"
        f'<div class="ev">Source S{f.source_id}: \u201c{escape(f.quote)}\u201d</div></li>'
        for f in s["superseded"]
    )
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    note = _resolved_note(state, handoff_note)
    handoff = mode == "handoff"
    report_type = "Handoff — work remains" if handoff else "Completed-work report"
    if note:
        note_html = f"<h2>Technician handoff note</h2><p>{escape(note)}</p>"
    else:
        note_html = (
            "<h2>Technician handoff note</h2>"
            '<p class="none-block">No handoff note was saved with this report.</p>'
        )
    open_section = _section(
        "Open problems and items to review",
        _open_facts(s),
        "No open problems or items to review.",
    )
    work_section = _section(
        "Work and test results recorded",
        _work_facts(s),
        "No completed work or test results recorded.",
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Handoff job {state.job.id}</title>
<style>
body{{font:15px/1.5 -apple-system,system-ui,sans-serif;color:#20282e;background:#fff;max-width:820px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:22px 0 8px;border-bottom:1px solid #e4e0d8;padding-bottom:4px}}
.meta{{color:#5c656c;font-size:14px;margin:0 0 4px}} .type{{font-size:16px;font-weight:650;margin:10px 0 16px}}
ul{{margin:0;padding-left:18px}} li{{margin:6px 0}}
.ev{{color:#5c656c;font-size:13px}} .corr{{color:#8a4b00}} .none,.none-block{{color:#78716c}}
.none{{list-style:none;margin-left:-18px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td{{border-bottom:1px solid #eee;padding:6px;vertical-align:top}}
.st{{font-weight:650;white-space:nowrap}} .st.reported,.st.not_applicable{{color:#1f5d32}} .st.conflicting,.st.unresolved{{color:#9b1c1c}}
.st.not_recorded,.st.planned,.st.not_complete{{color:#8a4b00}} .replaced{{color:#888}}
img.photo{{max-width:100%;height:auto;display:block;margin:6px 0;border:1px solid #e4e0d8}}
footer{{margin:28px 0 16px;padding-top:10px;border-top:1px solid #e4e0d8;color:#5c656c;font-size:12px}}
details{{margin-top:8px}}
@media print {{
  @page {{ size: auto; margin: 16mm 14mm; }}
  html, body {{
    background: #fff !important;
    color: #20282e !important;
    max-width: none;
    margin: 0;
    padding: 0;
    overflow: visible;
  }}
  h1, h2, h3, .type {{
    break-after: avoid;
    page-break-after: avoid;
  }}
  h2 + ul, h2 + table, h2 + p, .type + * {{
    break-before: avoid;
    page-break-before: avoid;
  }}
  p.meta, p.type, footer, tr {{
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  li:not(:has(img)) {{
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  ul, table, details {{
    break-inside: auto;
    overflow: visible;
  }}
  img.photo {{
    max-width: 100%;
    width: auto;
    height: auto;
    max-height: 12cm;
    object-fit: contain;
    break-inside: avoid;
    page-break-inside: avoid;
  }}
  details > summary {{
    break-after: avoid;
    page-break-after: avoid;
  }}
}}
</style></head><body>
<h1>Job {state.job.id} \u2014 {escape(state.job.title)}</h1>
{_asset_html(s)}
<p class="meta">Generated {generated} \u00b7 {escape(state.procedure_title)}</p>
<p class="type">{escape(report_type)}</p>
{open_section}
{work_section}
{_missing_html(state, s["planned_or_not_complete"])}
{note_html}
{_photos_html(state)}
<details>
<summary>Evidence and history</summary>
<h2>Checklist</h2><table>{rows}</table>
<h2>Earlier versions</h2><ul>{superseded or '<li class="none">No earlier versions.</li>'}</ul>
<h2>Sources</h2><ul>{sources or '<li class="none">No sources.</li>'}</ul>
</details>
<footer>{escape(r.disclaimer)} {escape(LOCAL_SAVE)}</footer>
</body></html>"""
