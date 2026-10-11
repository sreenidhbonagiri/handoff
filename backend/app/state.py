"""Deterministic validation and state transitions for model proposals.

The model proposes; this module decides. Checks cover schema shape, allowed states per field,
verbatim quotations, and permitted transitions. They do not prove the interpretation is right.
"""

import re
import sqlite3
from typing import Any

from pydantic import ValidationError

from . import db, evidence, mapping
from .photos import CAPTION_NOTE
from .schemas import ALLOWED_STATES, SINGLE_SLOT_FIELDS, Proposal, Rejection, Source

_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_QUOTE_MAP = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
_NUMBER_WORDS = {
    "zero": "0", "no": "0", "one": "1", "a": "1", "an": "1", "single": "1", "two": "2", "pair": "2",
    "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12",
}

# Transitions that a later statement may make without being flagged as a conflict.
_PROGRESSIONS = {
    ("planned", "reported_complete"),
    ("planned", "explicitly_not_complete"),
    ("unresolved", "resolved"),
    ("resolved", "unresolved"),
}
# Allowed only when the new statement comes from a different source than the existing fact.
_LATER_PROGRESSIONS = {
    ("explicitly_not_complete", "reported_complete"),
    ("explicitly_not_complete", "planned"),
}


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase, unify dashes/quotes, collapse whitespace (dropping it around dashes);
    keep a map back to original offsets."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch in _DASHES:
            ch = "-"
        ch = _QUOTE_MAP.get(ch, ch)
        if ch.isspace():
            if prev_space or (out and out[-1] == "-"):
                continue
            ch = " "
            prev_space = True
        else:
            if ch == "-" and out and out[-1] == " ":
                out.pop()
                index.pop()
            prev_space = False
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
        index.append(i)
    while out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


def locate_quote(source_text: str, quote: str | None) -> tuple[int, int] | None:
    if not quote:
        return None
    q = quote.strip().strip(" \"'.,;:!?")
    if not q:
        return None
    norm_source, offsets = _normalize_with_map(source_text)
    norm_quote, _ = _normalize_with_map(q)
    pos = norm_source.find(norm_quote)
    if pos < 0:
        return None
    return offsets[pos], offsets[pos + len(norm_quote) - 1] + 1


# Split a quote into clauses so an unrelated remark joined by "and" or a dash can be dropped.
# Unicode dashes always split; a hyphen only splits when it is spaced, so "drive-belt" stays intact.
_CLAUSE_SPLIT = re.compile(
    r"\s+(?:and|but|then)\s+|,\s+|;\s+|[\u2010-\u2015\u2212]\s*|(?<=\s)-(?=\s)"
)
_ALL_CLEAR_ITEM = re.compile(r"\bno (?:remaining|other|more|further|outstanding)\b")
_CONFIRM_NEEDS_TARGET = (
    "cannot confirm: this statement does not say which existing fact it replaces; "
    "edit it to name the item"
)


def _clause_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    last = 0
    for m in _CLAUSE_SPLIT.finditer(text):
        if m.start() > last:
            ranges.append((last, m.start()))
        last = m.end()
    if last < len(text):
        ranges.append((last, len(text)))
    return ranges or [(0, len(text))]


def _supports_claim(p: Proposal, frag: str, *, is_correction: bool, is_answer: bool) -> bool:
    """True when `frag` still names the item, carries the value, and supports the same state."""
    if not frag.strip():
        return False
    if p.item and p.field not in SINGLE_SLOT_FIELDS and not evidence.names_item(p.item, frag):
        return False
    if p.field == "asset_id" and p.value and p.value.lower() not in frag.lower():
        return False
    if p.value:
        nv = normalize_value(p.value)
        if p.field == "final_test":
            q = evidence._norm(frag)
            if nv == "passed" and (not evidence._PASS.search(q) or evidence._FAIL.search(q)):
                return False
            if nv == "failed" and not evidence._FAIL.search(q):
                return False
            if not evidence._TEST_WORDS.search(q):
                return False
        elif nv and nv.isdigit() and nv not in set(_numbers(frag)):
            return False
        elif p.field not in ("issue", "final_test") and p.value.lower() not in frag.lower() and nv not in set(_numbers(frag)):
            return False
    check = evidence.assess(
        p.field, p.state, p.value, p.item, frag, ALLOWED_STATES[p.field],
        is_correction=is_correction, is_answer=is_answer,
    )
    return check.reject is None and check.state == p.state


def tighten_span(
    source_text: str, span: tuple[int, int], p: Proposal, *, is_correction: bool, is_answer: bool,
) -> tuple[int, int]:
    """Keep the shortest clause sequence that still supports the claim, including negation."""
    start, end = span
    text = source_text[start:end]
    parts = _clause_ranges(text)
    if len(parts) <= 1:
        return span
    best: tuple[int, int, int] | None = None
    for i in range(len(parts)):
        for j in range(i, len(parts)):
            a, b = parts[i][0], parts[j][1]
            frag = text[a:b]
            lead, trail = len(frag) - len(frag.lstrip()), len(frag) - len(frag.rstrip())
            a, b = a + lead, b - trail
            if a >= b or not _supports_claim(p, text[a:b], is_correction=is_correction, is_answer=is_answer):
                continue
            length = b - a
            if best is None or length < best[0]:
                best = (length, start + a, start + b)
    return (best[1], best[2]) if best else span


def _original_quantity(source: Source, p: Proposal) -> tuple[str, tuple[int, int]] | None:
    """The quantity named by `corrects`, when that span is in the source and holds one value."""
    if not p.corrects:
        return None
    span = locate_quote(source.text, p.corrects)
    if span is None:
        return None
    found = [n for n in _numbers(source.text[span[0]:span[1]]) if n]
    new = normalize_value(p.value)
    olds = [n for n in found if n != new]
    if len(set(olds)) != 1:
        return None
    return olds[0], span


def _all_clear_claim(item: str | None, quote: str | None) -> bool:
    q = evidence._norm(quote or "")
    if evidence._ALL_CLEAR.search(q):
        return True
    return bool(item) and bool(_ALL_CLEAR_ITEM.search(item.lower()))


def _confirm_targets(facts: list[sqlite3.Row], chosen: sqlite3.Row) -> list[sqlite3.Row] | None:
    """Facts confirmation should supersede. None means the target cannot be determined."""
    targets: list[sqlite3.Row] = []
    seen: set[int] = set()
    if chosen["supersedes"] is not None:
        match = next((f for f in facts if f["id"] == chosen["supersedes"]), None)
        if match is not None:
            targets.append(match)
            seen.add(match["id"])
    for f in facts:
        if f["id"] == chosen["id"] or f["id"] in seen:
            continue
        if f["field"] == chosen["field"] and f["item_key"] == chosen["item_key"]:
            targets.append(f)
            seen.add(f["id"])
    if targets:
        return targets
    if chosen["field"] == "issue" and chosen["state"] == "resolved":
        open_issues = [
            f for f in facts
            if f["id"] != chosen["id"] and f["field"] == "issue" and f["state"] == "unresolved"
        ]
        if len(open_issues) == 1:
            return open_issues
        if open_issues and _all_clear_claim(chosen["item"], chosen["quote"]):
            return None
        if len(open_issues) > 1:
            return None
    return []


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def item_key(field: str, item: str | None) -> str:
    if field in SINGLE_SLOT_FIELDS or not item:
        return ""
    words = re.findall(r"[a-z0-9]+", item.lower())
    return " ".join(_singular(w) for w in words if w not in {"the", "a", "an"})


def normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    return _NUMBER_WORDS.get(v, v) or None


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4}


def _resolution_mentions_issue(issue: sqlite3.Row, quote: str) -> bool:
    """A resolution statement must name the problem it resolves (shared content word)."""
    reference = _stems(f"{issue['item'] or ''} {issue['quote']}")
    reference -= {"still", "there", "have", "with", "that", "this", "unit"}
    return bool(reference & _stems(quote))


def _numbers(text: str) -> list[str]:
    words = re.findall(r"[a-z]+|\d+", _normalize_with_map(text)[0])
    return [normalize_value(w) for w in words if w.isdigit() or (w in _NUMBER_WORDS and w not in {"a", "an", "no"})]


def _check_correction_value(p: Proposal, quote: str) -> tuple[Proposal, str | None, str | None]:
    """A correction must carry the new value. If the model repeated the corrected value and the quote
    contains exactly one other number after the corrected words, use it; otherwise hold for review.
    Returns (proposal, note, review)."""
    if not p.corrects or p.value is None:
        return p, None, None
    old = set(_numbers(p.corrects))
    if normalize_value(p.value) not in old:
        return p, None, None
    norm_quote, norm_corr = _normalize_with_map(quote)[0], _normalize_with_map(p.corrects)[0]
    pos = norm_quote.find(norm_corr)
    after = set(_numbers(norm_quote[pos + len(norm_corr):])) - old if pos >= 0 else set()
    if len(after) == 1:
        new = after.pop()
        return p.model_copy(update={"value": new}), f"value {new} taken from the words after \u201c{p.corrects}\u201d", None
    return p, None, "the corrected value repeats the value being corrected; confirm the quantity"


def _join(*notes: str | None) -> str | None:
    return "; ".join(n for n in notes if n) or None


def _find_target(facts: list[sqlite3.Row], p: Proposal, key: str, source: Source) -> tuple[sqlite3.Row | None, str | None]:
    note = None
    if p.target_fact_id is not None:
        match = next((f for f in facts if f["id"] == p.target_fact_id), None)
        if match is not None and match["field"] == p.field:
            return match, None
        note = f"target_fact_id {p.target_fact_id} ignored (not an active {p.field} fact)"

    same_key = [f for f in facts if f["field"] == p.field and f["item_key"] == key]
    if same_key:
        return same_key[-1], note

    if p.corrects:
        corrected = _normalize_with_map(p.corrects)[0]
        for f in reversed(facts):
            if f["field"] == p.field and corrected and corrected in _normalize_with_map(f["quote"])[0]:
                return f, note
    return None, note


def _insert_from_proposal(
    conn: sqlite3.Connection, job_id: int, source: Source, p: Proposal, span: tuple[int, int],
    item: str | None, **extra: Any,
) -> int:
    return db.insert_fact(
        conn,
        job_id=job_id,
        source_id=source.id,
        field=p.field,
        item=item,
        item_key=item_key(p.field, item),
        value=p.value,
        state=p.state,
        quote=source.text[span[0]:span[1]],
        quote_start=span[0],
        quote_end=span[1],
        **extra,
    )


def _supersede(conn: sqlite3.Connection, facts: list[sqlite3.Row], existing: sqlite3.Row, new_id: int) -> None:
    """Supersede a fact, every other side of its conflict, and any unclear statement held for
    review about the same item: a clear later statement settles them all."""
    group = existing["conflict_group"]
    for f in facts:
        if f["id"] == new_id:
            continue
        held_same_item = (
            f["review_status"] == "needs_review" and f["field"] == existing["field"] and f["item_key"] == existing["item_key"]
        )
        if f["id"] == existing["id"] or (group is not None and f["conflict_group"] == group) or held_same_item:
            db.update_fact(conn, f["id"], superseded_by=new_id)


def _mark_conflict(conn: sqlite3.Connection, job_id: int, existing: sqlite3.Row, new_id: int, reason: str) -> None:
    group = existing["conflict_group"] or db.next_conflict_group(conn, job_id)
    db.update_fact(conn, existing["id"], review_status="conflicting", conflict_group=group)
    db.update_fact(conn, new_id, review_status="conflicting", conflict_group=group, note=reason)


def _apply_one(
    conn: sqlite3.Connection, job_id: int, source: Source, p: Proposal, span: tuple[int, int], clarify: str | None = None,
) -> str | None:
    """Apply one validated proposal. Returns a reason string if it was not applied.
    `clarify` holds the fact for review because its target record is ambiguous."""
    facts = db.active_fact_rows(conn, job_id)
    key = item_key(p.field, p.item)
    p, value_note, value_review = _check_correction_value(p, source.text[span[0]:span[1]])
    clarify = _join(clarify, value_review)
    span = tighten_span(
        source.text, span, p, is_correction=bool(p.corrects), is_answer=source.kind == "answer",
    )
    check = evidence.assess(
        p.field, p.state, p.value, p.item, source.text[span[0]:span[1]], ALLOWED_STATES[p.field],
        is_correction=bool(p.corrects), is_answer=source.kind == "answer",
    )
    if check.reject:
        return check.reject
    if check.state != p.state:
        p = p.model_copy(update={"state": check.state})
    existing, note = _find_target(facts, p, key, source)
    note = _join(note, check.note, value_note)
    if source.kind == "photo":
        note = _join(note, CAPTION_NOTE)
    review = _join(clarify, check.review)
    if p.field == "issue" and p.state == "resolved" and _all_clear_claim(p.item, source.text[span[0]:span[1]]):
        named_open = [
            f for f in facts
            if f["field"] == "issue" and f["state"] == "unresolved" and not _all_clear_claim(f["item"], f["quote"])
        ]
        if named_open and not any(_resolution_mentions_issue(f, source.text[span[0]:span[1]]) for f in named_open):
            review = _join(review, "an open issue is already recorded; confirm whether it is resolved")

    if review:
        if not clarify and existing is not None and existing["state"] == p.state and (
            normalize_value(existing["value"]) == normalize_value(p.value)
        ):
            return f"no change: restates active fact {existing['id']}"
        # Held for review: stored and shown, but nothing is superseded until a person confirms it.
        # `supersedes` records which fact confirmation would replace.
        intended = existing
        if intended is None and p.field == "issue" and p.state == "resolved":
            open_issues = [f for f in facts if f["field"] == "issue" and f["state"] == "unresolved"]
            if len(open_issues) == 1:
                intended = open_issues[0]
            elif open_issues:
                review = _join(review, "several issues are open; say which one is resolved")
        _insert_from_proposal(
            conn, job_id, source, p, span, p.item or (existing["item"] if existing else None),
            corrected_from=p.corrects, review_status="needs_review", note=_join(review, note),
            supersedes=intended["id"] if intended is not None else None,
        )
        return None

    if existing is None:
        corrected_from = p.corrects if p.corrects and locate_quote(source.text, p.corrects) else None
        original = _original_quantity(source, p) if p.corrects else None
        if original is not None:
            old_value, old_span = original
            old_id = _insert_from_proposal(
                conn, job_id, source, p.model_copy(update={"value": old_value, "corrects": None}),
                old_span, p.item,
            )
            new_id = _insert_from_proposal(
                conn, job_id, source, p, span, p.item,
                corrected_from=p.corrects, supersedes=old_id, note=note,
            )
            db.update_fact(conn, old_id, superseded_by=new_id)
            return None
        _insert_from_proposal(conn, job_id, source, p, span, p.item, corrected_from=corrected_from, note=note)
        return None

    item = p.item or existing["item"]

    if p.corrects:
        new_id = _insert_from_proposal(
            conn, job_id, source, p, span, item,
            corrected_from=p.corrects, supersedes=existing["id"], note=note,
        )
        _supersede(conn, facts, existing, new_id)
        return None

    same_value = normalize_value(existing["value"]) == normalize_value(p.value)
    if same_value and existing["state"] == p.state:
        return f"no change: restates active fact {existing['id']}"

    transition = (existing["state"], p.state)
    is_progression = transition in _PROGRESSIONS or (
        transition in _LATER_PROGRESSIONS and existing["source_id"] != source.id
    )
    adds_detail = existing["state"] == p.state and existing["value"] is None and p.value is not None
    # A state progression may also fill in a result (planned test -> passed), but must not change
    # a value that was already recorded (two filters -> three filters needs an explicit correction).
    value_compatible = existing["value"] is None or same_value

    if p.field == "issue" and transition == ("unresolved", "resolved"):
        if not _resolution_mentions_issue(existing, source.text[span[0]:span[1]]):
            new_id = _insert_from_proposal(conn, job_id, source, p, span, item, note=note)
            _mark_conflict(
                conn, job_id, existing, new_id,
                "resolution statement does not name this issue; confirm whether it is resolved",
            )
            return None

    if (is_progression and value_compatible) or adds_detail:
        new_id = _insert_from_proposal(conn, job_id, source, p, span, item, supersedes=existing["id"], note=note)
        _supersede(conn, facts, existing, new_id)
        return None

    new_id = _insert_from_proposal(conn, job_id, source, p, span, item, note=note)
    _mark_conflict(conn, job_id, existing, new_id, "differs from an earlier statement without an explicit correction")
    return None


def apply_extraction(conn: sqlite3.Connection, job_id: int, source: Source, raw_items: list[Any]) -> list[Rejection]:
    rejections: list[Rejection] = []
    for raw, clarify in mapping.map_proposals(db.active_fact_rows(conn, job_id), raw_items):
        raw_dict = raw if isinstance(raw, dict) else {"value": raw}
        try:
            p = Proposal.model_validate(raw)
        except ValidationError as e:
            rejections.append(Rejection(source_id=source.id, proposal=raw_dict, reason=f"schema: {e.errors()[0]['msg']}"))
            continue
        if p.state not in ALLOWED_STATES[p.field]:
            rejections.append(Rejection(source_id=source.id, proposal=raw_dict, reason=f"state {p.state} not allowed for {p.field}"))
            continue
        span = locate_quote(source.text, p.quote)
        if span is None:
            rejections.append(Rejection(source_id=source.id, proposal=raw_dict, reason="quote is not an exact substring of the source"))
            continue
        resolved, span, clarify = mapping.resolve_test_result(
            source.text, p.model_dump(), span, db.active_fact_rows(conn, job_id), clarify,
        )
        try:
            p = Proposal.model_validate(resolved)
        except ValidationError as e:
            rejections.append(Rejection(source_id=source.id, proposal=raw_dict, reason=f"schema: {e.errors()[0]['msg']}"))
            continue
        reason = _apply_one(conn, job_id, source, p, span, clarify)
        if reason:
            rejections.append(Rejection(source_id=source.id, proposal=raw_dict, reason=reason))
    return rejections


def confirm_fact(conn: sqlite3.Connection, job_id: int, fact_id: int) -> None:
    """User picks one fact in a conflict group, or accepts a fact held for review; whatever it
    replaces is superseded by it."""
    facts = db.active_fact_rows(conn, job_id)
    chosen = next((f for f in facts if f["id"] == fact_id), None)
    if chosen is not None and chosen["review_status"] == "needs_review":
        targets = _confirm_targets(facts, chosen)
        if targets is None:
            raise ValueError(_CONFIRM_NEEDS_TARGET)
        extras: dict[str, Any] = {"review_status": "confirmed"}
        if chosen["supersedes"] is None and len(targets) == 1:
            extras["supersedes"] = targets[0]["id"]
        for f in targets:
            _supersede(conn, facts, f, fact_id)
        db.update_fact(conn, fact_id, **extras)
        return
    if chosen is None or chosen["conflict_group"] is None:
        raise ValueError("fact is not an active conflicting fact or a fact awaiting review")
    for f in facts:
        if f["conflict_group"] == chosen["conflict_group"] and f["id"] != fact_id:
            db.update_fact(conn, f["id"], superseded_by=fact_id)
    db.update_fact(conn, fact_id, review_status="confirmed")


def review_fact(conn: sqlite3.Connection, job_id: int, fact_id: int, value: str | None, state: str) -> None:
    """A reviewer edit becomes its own source so the change stays traceable."""
    facts = db.active_fact_rows(conn, job_id)
    target = next((f for f in facts if f["id"] == fact_id), None)
    if target is None:
        raise ValueError("fact is not active")
    if state not in ALLOWED_STATES[target["field"]]:
        raise ValueError(f"state {state} not allowed for {target['field']}")
    label = target["field"] + (f" ({target['item']})" if target["item"] else "")
    text = f"Reviewer set {label} to value={value if value is not None else 'none'}, state={state}."
    source = db.insert_source(conn, job_id, "review", text)
    new_id = db.insert_fact(
        conn,
        job_id=job_id,
        source_id=source.id,
        field=target["field"],
        item=target["item"],
        item_key=target["item_key"],
        value=value,
        state=state,
        quote=text,
        quote_start=0,
        quote_end=len(text),
        supersedes=fact_id,
        review_status="confirmed",
    )
    _supersede(conn, facts, target, new_id)


def invalidate_source(conn: sqlite3.Connection, job_id: int, source_id: int) -> None:
    """Drop interpretations from an edited transcript and restore what they had superseded."""
    all_rows = conn.execute("SELECT * FROM fact_revisions WHERE job_id = ?", (job_id,)).fetchall()
    dropped = {r["id"] for r in all_rows if r["source_id"] == source_id and not r["invalidated"]}
    for fid in dropped:
        db.update_fact(conn, fid, invalidated=1)
    for r in all_rows:
        if r["superseded_by"] in dropped:
            db.update_fact(conn, r["id"], superseded_by=None)
    groups: dict[int, list[sqlite3.Row]] = {}
    for r in db.active_fact_rows(conn, job_id):
        if r["conflict_group"] is not None:
            groups.setdefault(r["conflict_group"], []).append(r)
    for members in groups.values():
        if len(members) == 1 and members[0]["review_status"] == "conflicting":
            db.update_fact(conn, members[0]["id"], review_status="accepted", conflict_group=None)
