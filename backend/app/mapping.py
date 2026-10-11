"""Map model `test` proposals onto job records using the job's checklist and existing facts.

The model only says that a statement is about a test, and names the test if the note does.
Which record it updates is decided here:
- a named final/functional test -> final_test (checklist R3)
- another named test ("pressure test") -> other_action with that name
- an unnamed test ("tested it") -> the single plausible test in the job, or a clarification
  request when several tests are plausible.
"""

import re
import sqlite3
from typing import Any

from . import evidence

_TEST_WORDS = re.compile(r"\b(?:test\w*|check\w*|trial|run|ran|running|commission\w*)\b")
_GENERIC_WORDS = {
    "the", "a", "an", "it", "its", "test", "tests", "testing", "tested", "check", "checks", "checked",
    "checking", "run", "ran", "unit", "this", "that", "again", "do", "did", "done", "of",
}
_FINAL_WORDS = {"final", "functional", "closeout", "close", "commissioning", "operational", "operation", "acceptance"}

FINAL_TEST_NAME = "final functional test"


def _words(text: str | None) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def is_test_name(item: str | None) -> bool:
    return bool(item) and bool(_TEST_WORDS.search(item.lower()))


# A named test is a qualifier directly before the test word: "pressure test", "leak check".
_NAMED_TEST = re.compile(r"(?<!['\u2019])\b([a-z]{3,})\s+(test|check|trial)s?\b")
_NOT_QUALIFIERS = _GENERIC_WORDS | {"to", "will", "need", "and", "i", "we", "not", "another", "one", "more", "first"}


def _named_test(text: str | None) -> str | None:
    for m in _NAMED_TEST.finditer((text or "").lower()):
        if m.group(1) not in _NOT_QUALIFIERS:
            return f"{m.group(1)} {m.group(2)}"
    return None


def _test_kind(item: str | None, quote: str) -> tuple[str, str | None]:
    """('final', None), ('other', name) or ('generic', None)."""
    if set(_words(item)) & _FINAL_WORDS or set(_words(quote)) & _FINAL_WORDS:
        return "final", None
    name = _named_test(item)
    if name:
        return "other", name
    return "generic", None


def other_tests_in_job(active: list[sqlite3.Row]) -> list[str]:
    return [r["item"] for r in active if r["field"] == "other_action" and is_test_name(r["item"])]


def _as_test(raw: Any) -> Any:
    """A test is an action, so the model sometimes files it under other_action; route those here too."""
    if isinstance(raw, dict) and raw.get("field") == "other_action" and is_test_name(raw.get("item")):
        return {**raw, "field": "test"}
    return raw


def result_value(quote: str) -> str | None:
    """passed/failed when the quote states a result; failed wins if both cues appear."""
    q = evidence._norm(quote)
    if evidence._FAIL.search(q):
        return "failed"
    if evidence._PASS.search(q):
        return "passed"
    return None


def tests_mentioned(text: str) -> list[str]:
    """Specific tests named in text, in order of appearance."""
    found: list[str] = []
    for m in _NAMED_TEST.finditer((text or "").lower()):
        if m.group(1) in _FINAL_WORDS:
            name = FINAL_TEST_NAME
        elif m.group(1) not in _NOT_QUALIFIERS:
            name = f"{m.group(1)} {m.group(2)}"
        else:
            continue
        if name not in found:
            found.append(name)
    return found


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    start = 0
    for m in re.finditer(r"[.!?]+[\s]*", text[: max(pos, 0)]):
        start = m.end()
    end = len(text)
    m = re.search(r"[.!?]", text[pos:])
    if m:
        end = pos + m.end()
    return start, end


def surrounding_window(text: str, start: int, end: int) -> tuple[int, int]:
    """The sentence containing `start`, plus the sentence before it."""
    this_start, this_end = _sentence_bounds(text, start)
    if this_start == 0:
        return 0, max(this_end, end)
    i = this_start - 1
    while i > 0 and text[i] in ".!? \t\n":
        i -= 1
    prev_start, _ = _sentence_bounds(text, i)
    return prev_start, max(this_end, end)


def _cover_test_and_result(text: str, window: tuple[int, int], result: tuple[int, int], name: str) -> tuple[int, int]:
    """Span from the sentence that names `name` through the result fragment."""
    chunk = text[window[0]:window[1]]
    if name == FINAL_TEST_NAME:
        m = re.search(
            r"\b(?:final|functional|closeout|commissioning|operational|acceptance)\b(?:\s+\w+){0,3}\s+(?:test|check)s?\b",
            chunk, re.I,
        )
    else:
        m = re.search(rf"\b{re.escape(name)}s?\b", chunk, re.I)
    if not m:
        return result
    mention_at = window[0] + m.start()
    sent_start, _ = _sentence_bounds(text, mention_at)
    return sent_start, max(window[0] + m.end(), result[1])


def _options(names: list[str]) -> str:
    return " or ".join(f"the {n}" for n in names)


def _bind_test(raw: dict[str, Any], name: str, value: str) -> dict[str, Any]:
    bound = {**raw, "value": raw.get("value") or value}
    if name == FINAL_TEST_NAME:
        bound.update(field="final_test", item=None)
    else:
        bound.update(field="other_action", item=name)
    return bound


def resolve_test_result(
    source_text: str, raw: dict[str, Any], span: tuple[int, int],
    active: list[sqlite3.Row], clarify: str | None,
) -> tuple[dict[str, Any], tuple[int, int], str | None]:
    """Attach a result-only test fragment to the unique nearby or job test; hold if several fit."""
    if raw.get("field") not in ("final_test", "other_action", "test"):
        return raw, span, clarify
    if raw.get("field") == "other_action" and not is_test_name(raw.get("item")):
        return raw, span, clarify
    quote = source_text[span[0]:span[1]]
    result = result_value(quote)
    if not result:
        return raw, span, clarify
    if tests_mentioned(quote):
        if raw.get("value") is None:
            raw = {**raw, "value": result}
        return raw, span, clarify

    window = surrounding_window(source_text, span[0], span[1])
    nearby = tests_mentioned(source_text[window[0]:window[1]])
    if len(nearby) > 1:
        return raw, span, "; ".join(
            n for n in (clarify, f"several tests are plausible; which test does this refer to: {_options(nearby)}?") if n
        )
    if len(nearby) == 1:
        name = nearby[0]
        covered = _cover_test_and_result(source_text, window, span, name)
        return _bind_test(raw, name, result), covered, None

    job: list[str] = []
    if any(f["field"] == "final_test" for f in active):
        job.append(FINAL_TEST_NAME)
    for name in other_tests_in_job(active):
        if name not in job:
            job.append(name)
    if len(job) == 1:
        return _bind_test(raw, job[0], result), span, None
    if len(job) > 1:
        return raw, span, "; ".join(
            n for n in (clarify, f"several tests are plausible; which test does this refer to: {_options(job)}?") if n
        )
    return raw, span, "; ".join(n for n in (clarify, "which test does this result refer to?") if n)


def map_proposals(active: list[sqlite3.Row], raw_items: list[Any]) -> list[tuple[Any, str | None]]:
    """Return (proposal, clarification) pairs. A clarification means the proposal must be held."""
    items = [_as_test(r) for r in raw_items]
    named_here = []
    for raw in items:
        if isinstance(raw, dict) and raw.get("field") == "test":
            kind, name = _test_kind(raw.get("item"), raw.get("quote") or "")
            if kind == "other":
                named_here.append(name)

    out: list[tuple[Any, str | None]] = []
    for raw in items:
        if not (isinstance(raw, dict) and raw.get("field") == "test"):
            out.append((raw, None))
            continue
        kind, name = _test_kind(raw.get("item"), raw.get("quote") or "")
        if kind == "other":
            out.append(({**raw, "field": "other_action", "item": name}, None))
            continue
        mapped = {**raw, "field": "final_test", "item": None}
        if kind == "final":
            out.append((mapped, None))
            continue
        # A result-only fragment is bound from the surrounding sentence in resolve_test_result.
        if result_value(raw.get("quote") or ""):
            out.append((mapped, None))
            continue
        others = list(dict.fromkeys(other_tests_in_job(active) + named_here))
        if not others:
            out.append((mapped, None))
            continue
        options = " or ".join([f"the {FINAL_TEST_NAME}"] + [f"the {o}" for o in others])
        out.append((mapped, f"several tests are plausible; which test does this refer to: {options}?"))
    return out
