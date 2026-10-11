"""Shared API contract. frontend/src/types.ts mirrors these models by hand."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

FieldName = Literal["asset_id", "part_replaced", "final_test", "issue", "follow_up", "other_action"]
FactState = Literal[
    "reported_complete", "planned", "explicitly_not_complete", "unresolved", "resolved", "observed"
]
ReviewStatus = Literal["accepted", "conflicting", "needs_review", "confirmed"]
SourceKind = Literal["typed", "voice", "answer", "review", "photo"]
RequirementState = Literal[
    "reported", "planned", "not_recorded", "not_complete", "conflicting", "unresolved", "not_applicable"
]

ALLOWED_STATES: dict[str, set[str]] = {
    "asset_id": {"observed"},
    "part_replaced": {"reported_complete", "planned", "explicitly_not_complete"},
    "final_test": {"reported_complete", "planned", "explicitly_not_complete"},
    "issue": {"unresolved", "resolved"},
    "follow_up": {"reported_complete", "planned"},
    "other_action": {"reported_complete", "planned", "explicitly_not_complete"},
}

# Fields with one value per job; the item name does not distinguish entries.
SINGLE_SLOT_FIELDS = {"asset_id", "final_test"}


class Proposal(BaseModel):
    """One candidate change proposed by the model. Every key is required (nullable) so the
    constrained output always has the same shape."""

    field: FieldName
    item: str | None
    value: str | None
    state: FactState
    quote: str
    corrects: str | None
    target_fact_id: int | None


ModelFieldName = Literal["asset_id", "part_replaced", "test", "issue", "follow_up", "other_action"]


class ModelProposal(BaseModel):
    """Shape of one model proposal (see model_output_schema for the decoding constraint). The quote
    comes first so the field and state are chosen after the evidence is written. `test` covers any
    test; mapping.py decides which test it is from the job's checklist and facts."""

    quote: str
    field: ModelFieldName
    item: str | None
    value: str | None
    state: FactState
    corrects: str | None
    target_fact_id: int | None


class ExtractionResult(BaseModel):
    proposals: list[ModelProposal]


MODEL_ALLOWED_STATES: dict[str, set[str]] = {
    **{k: v for k, v in ALLOWED_STATES.items() if k != "final_test"},
    "test": ALLOWED_STATES["final_test"],
}


def model_output_schema() -> dict[str, Any]:
    """JSON schema for constrained decoding: one branch per field, each allowing only that field's
    states, so the model cannot produce e.g. an issue that is "explicitly_not_complete"."""
    order = ["quote", "field", "state", "item", "value", "corrects", "target_fact_id"]
    nullable = {"type": ["string", "null"]}
    branches = []
    for field, states in MODEL_ALLOWED_STATES.items():
        props = {
            "quote": {"type": "string"}, "field": {"const": field}, "state": {"enum": sorted(states)},
            "item": nullable, "value": nullable, "corrects": nullable,
            "target_fact_id": {"type": ["integer", "null"]},
        }
        branches.append({"type": "object", "properties": {k: props[k] for k in order}, "required": order})
    return {
        "type": "object",
        "properties": {"proposals": {"type": "array", "items": {"anyOf": branches}}},
        "required": ["proposals"],
    }


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class ObservationIn(BaseModel):
    text: str = Field(default="", max_length=4000)
    kind: Literal["typed", "voice", "answer", "photo"] = "typed"
    answers_requirement: str | None = None
    audio_path: str | None = None
    photo_path: str | None = None
    segments: list[Segment] | None = None
    # Whisper output before the user's review; `text` is the reviewed version that gets extracted.
    original_transcript: str | None = Field(default=None, max_length=4000)
    transcription_ms: float | None = None

    @model_validator(mode="after")
    def _source_payload(self) -> "ObservationIn":
        if self.kind == "photo":
            if not (self.photo_path and self.photo_path.strip()):
                raise ValueError("photo observations must include the stored photo path")
            return self
        if not self.text.strip():
            raise ValueError("text must not be blank")
        if self.kind == "voice" and not (self.original_transcript and self.original_transcript.strip()):
            raise ValueError("voice observations must include the original transcript")
        return self


class SourceEditIn(BaseModel):
    text: str = Field(default="", max_length=4000)


class FactReviewIn(BaseModel):
    value: str | None
    state: FactState


class Job(BaseModel):
    id: int
    title: str
    created_at: str
    handoff_note: str | None = None
    location: str | None = None
    updated_at: str | None = None


class HandoffNoteIn(BaseModel):
    note: str = Field(default="", max_length=4000)


class Source(BaseModel):
    id: int
    job_id: int
    kind: SourceKind
    text: str
    created_at: str
    audio_path: str | None
    photo_path: str | None = None
    segments: list[Segment] | None
    answers_requirement: str | None
    revises: int | None
    replaced_by: int | None
    original_transcript: str | None
    transcription_ms: float | None
    extraction_ms: float | None


class Fact(BaseModel):
    id: int
    source_id: int
    field: FieldName
    item: str | None
    value: str | None
    state: FactState
    quote: str
    quote_start: int
    quote_end: int
    corrected_from: str | None
    supersedes: int | None
    superseded_by: int | None
    review_status: ReviewStatus
    conflict_group: int | None
    invalidated: bool
    active: bool
    note: str | None
    created_at: str


class Rejection(BaseModel):
    source_id: int
    proposal: dict[str, Any]
    reason: str


class RunInfo(BaseModel):
    id: int
    source_id: int
    model: str
    ok: bool
    error: str | None
    wall_ms: float | None
    total_ms: float | None
    load_ms: float | None
    prompt_tokens: int | None
    eval_tokens: int | None
    eval_ms: float | None
    created_at: str


class RequirementStatus(BaseModel):
    id: str
    section: str
    label: str
    status: RequirementState
    satisfied: bool
    detail: str
    fact_ids: list[int]


class Question(BaseModel):
    requirement_id: str
    text: str
    fact_ids: list[int]


class Readiness(BaseModel):
    ready: bool
    summary: str
    disclaimer: str


class JobState(BaseModel):
    job: Job
    procedure_title: str
    sources: list[Source]
    facts: list[Fact]
    checklist: list[RequirementStatus]
    next_question: Question | None
    readiness: Readiness
    last_run: RunInfo | None
    rejected: list[Rejection]


class JobListItem(BaseModel):
    """Dashboard row: saved job plus its facts so the UI can reuse review-panel counts."""

    job: Job
    facts: list[Fact]


class Health(BaseModel):
    ollama_reachable: bool
    model: str
    model_installed: bool
    quantization: str | None
    parameter_size: str | None
    device: str
    ffmpeg_available: bool
    whisper_available: bool
    whisper_model: str
    error: str | None


class TranscribeOut(BaseModel):
    text: str
    segments: list[Segment]
    audio_path: str
    duration_ms: int
    peak_db: float | None
    convert_ms: float
    whisper_ms: float
    wall_ms: float
    model: str
