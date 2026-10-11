"""Check that a quote's wording supports the state a proposal claims.

A verbatim quote proves the words were said, not what they mean. These rules look for cues
(intent, non-completion, persistence, resolution, test result) in the quoted words. When the
wording clearly supports a different state the proposal is re-labelled with a visible note;
when it is ambiguous the fact is held for review and does not count toward the checklist.
"""

import re
from dataclasses import dataclass

_INTENT = re.compile(
    r"\b(?:need(?:s|ed)? to|have to|has to|got to|gotta|going to|gonna|will|shall|plan(?:s|ned|ning)? to|"
    r"intend(?:s|ed)? to|want(?:s)? to|should|must|tomorrow|later|next (?:visit|time|week|shift|day)|"
    r"continue|pending|to be (?:done|replaced|fixed|repaired|tested|completed|checked)|schedul(?:e|ed|ing))\b"
    r"|'ll\b"
)
_NOT_DONE = re.compile(
    r"\b(?:haven't|hasn't|hadn't|didn't|couldn't|can't|cannot|wasn't|weren't|isn't|aren't|won't|"
    r"have not|has not|had not|did not|could not|can not|was not|were not|is not|are not|will not|"
    r"not yet|not done|not finished|not completed?|unable to|failed to|skipped|never)\b"
)
_PERSISTS = re.compile(
    r"\b(?:still|persists?|persisting|remains?|remaining|keeps?|continues? to|again|came back|returned)\b"
)
_RESOLVED = re.compile(
    r"\b(?:fixed|repaired|resolved|solved|stopped|gone|cleared|eliminated|corrected|sealed|sorted|"
    r"no longer|anymore|any more|no more|went away|disappeared|(?:fine|ok|okay|working|works) now)\b"
)
_ALL_CLEAR = re.compile(
    r"\bno (?:remaining |other |more |further |outstanding )?(?:issues?|problems?|faults?|defects?)\b"
    r"|\bnothing (?:else )?(?:wrong|remaining)\b"
)
# Negations that state a resolution ("not leaking anymore") rather than deny one.
_NOT_ANYMORE = re.compile(r"\b(?:not|isn't|aren't|doesn't|don't)\b[^.,;]*?\b(?:anymore|any more)\b")
# A resolution word governed by a negation ("haven't fixed", "not repaired yet") is not a resolution.
_NEGATED_RESOLUTION = re.compile(
    r"\b(?:not|never|haven't|hasn't|hadn't|didn't|couldn't|wasn't|weren't|isn't|aren't|won't)\b(?:\s+\S+){0,3}"
)
_PASS = re.compile(r"\b(?:pass(?:ed|es)?|ok|okay|good|fine|success(?:ful(?:ly)?)?|succeeded|normal|within spec)\b")
_FAIL = re.compile(r"\b(?:fail(?:ed|s)?|didn't pass|did not pass|unsuccessful|out of spec)\b")
# Requests and instructions about the record are not reports of work done.
_REQUEST = re.compile(
    r"\b(?:go ahead and|please|can you|could you|let's|mark (?:this|the|it|job)\b[^.]*\b(?:complete|done|closed)|close (?:out )?(?:this|the) job)\b"
)
# A report of work done names a performed action: a past-tense verb or a common irregular one.
_PERFORMED = re.compile(r"\b(?:[a-z]+ed|ran|did|done|put|set|fit|got|took|rebuilt|built|reset|made|redone|swept)\b")
_TEST_WORDS = re.compile(r"\b(?:test\w*|check\w*|trial|run|ran|running|commission\w*)\b")


@dataclass
class Assessment:
    state: str
    review: str | None = None  # set when the fact must be confirmed before it counts
    note: str | None = None  # set when the state was re-labelled from the wording
    reject: str | None = None  # set when the quote cannot support this kind of fact at all


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").replace("\u2018", "'").split())


def _stems(text: str) -> set[str]:
    # Four-letter stems so plurals and inflections match ("pipe"/"pipes", "rattle"/"rattling").
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:4] for w in words if len(w) >= 3} - {"the", "and", "for", "with", "that", "this", "unit"}


def names_item(item: str | None, quote: str) -> bool:
    return bool(item) and bool(_stems(item) & _stems(quote))


def assess(field: str, state: str, value: str | None, item: str | None, quote: str, allowed: set[str],
           *, is_correction: bool, is_answer: bool) -> Assessment:
    q = _norm(quote)
    all_clear = bool(_ALL_CLEAR.search(q) or _NOT_ANYMORE.search(q))
    rest = _NOT_ANYMORE.sub(" ", _ALL_CLEAR.sub(" ", q))
    intent = bool(_INTENT.search(rest))
    not_done = bool(_NOT_DONE.search(rest))
    persists = bool(_PERSISTS.search(rest))
    resolved_cue = all_clear or bool(_RESOLVED.search(_NEGATED_RESOLUTION.sub(" ", rest)))

    result_fragment = bool(value) and (
        (value.lower() == "failed" and bool(_FAIL.search(q)))
        or (value.lower() == "passed" and bool(_PASS.search(q)) and not _FAIL.search(q))
    )
    if field == "final_test" and not is_answer and not _TEST_WORDS.search(q) and not result_fragment:
        return Assessment(state, reject="quote does not mention a test")
    if state in ("reported_complete", "resolved") and _REQUEST.search(q):
        return Assessment(state, reject="quote is a request or instruction, not a report of work done")

    if field == "issue":
        if state != "resolved":
            return Assessment(state)
        blocking = intent or not_done or persists
        if blocking and not resolved_cue:
            return Assessment("unresolved", note="re-labelled unresolved: the quote states remaining work or a persisting problem, not a resolution")
        if blocking:
            return Assessment(state, review="the quote mixes resolution and remaining-work wording; confirm whether this issue is resolved")
        if not resolved_cue:
            return Assessment(state, review="the quote does not explicitly say this issue was resolved; confirm before it counts")
        if not all_clear and not names_item(item, quote) and not is_answer:
            return Assessment(state, review="the quote does not name the issue it resolves; confirm which issue is resolved")
        return Assessment(state)

    if state == "reported_complete":
        if not_done and "explicitly_not_complete" in allowed:
            return Assessment("explicitly_not_complete", note="re-labelled not done: the quote says this was not done")
        if not_done:
            return Assessment(state, review="the quote says this was not done; confirm before it counts")
        if intent and "planned" in allowed:
            return Assessment("planned", note="re-labelled planned: the quote states intent or remaining work, not completion")
        if field == "final_test" and value:
            v = value.lower()
            if (v == "passed" and (not _PASS.search(q) or _FAIL.search(q))) or (v == "failed" and not _FAIL.search(q)):
                return Assessment(state, review=f"the quote does not state that the test {v}; confirm the result")
        if field in ("part_replaced", "other_action") and not is_correction and not is_answer and not result_fragment:
            if not names_item(item, quote):
                return Assessment(state, review="the quote does not say what was completed; confirm before it counts")
            if not _PERFORMED.search(q):
                return Assessment(state, review="the quote does not describe an action that was performed; confirm before it counts")
        return Assessment(state)

    if state == "planned" and not_done and not intent and "explicitly_not_complete" in allowed:
        return Assessment("explicitly_not_complete", note="re-labelled not done: the quote says this has not been done and gives no plan")
    if state == "explicitly_not_complete" and intent and not not_done and "planned" in allowed:
        return Assessment("planned", note="re-labelled planned: the quote states a plan, not that the work was skipped")
    return Assessment(state)
