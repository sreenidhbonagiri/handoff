// Hand-written mirror of backend/app/schemas.py. Change only after the backend contract changes.

export type FieldName = "asset_id" | "part_replaced" | "final_test" | "issue" | "follow_up" | "other_action";
export type FactState =
  | "reported_complete"
  | "planned"
  | "explicitly_not_complete"
  | "unresolved"
  | "resolved"
  | "observed";
export type ReviewStatus = "accepted" | "conflicting" | "needs_review" | "confirmed";
export type SourceKind = "typed" | "voice" | "answer" | "review" | "photo";
export type RequirementState =
  | "reported"
  | "planned"
  | "not_recorded"
  | "not_complete"
  | "conflicting"
  | "unresolved"
  | "not_applicable";

export const ALLOWED_STATES: Record<FieldName, FactState[]> = {
  asset_id: ["observed"],
  part_replaced: ["reported_complete", "planned", "explicitly_not_complete"],
  final_test: ["reported_complete", "planned", "explicitly_not_complete"],
  issue: ["unresolved", "resolved"],
  follow_up: ["reported_complete", "planned"],
  other_action: ["reported_complete", "planned", "explicitly_not_complete"],
};

export interface Segment {
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface ObservationIn {
  text: string;
  kind: "typed" | "voice" | "answer" | "photo";
  answers_requirement?: string | null;
  audio_path?: string | null;
  photo_path?: string | null;
  segments?: Segment[] | null;
  original_transcript?: string | null;
  transcription_ms?: number | null;
}

export interface Job {
  id: number;
  title: string;
  created_at: string;
  handoff_note: string | null;
  location: string | null;
  updated_at: string | null;
}

export interface JobListItem {
  job: Job;
  facts: Fact[];
}

export type PinStatus = "open_problem" | "needs_attention" | "no_open_items";

export interface JobPin {
  job_id: number;
  x: number;
  y: number;
}

export interface SitePlan {
  name: string | null;
  image_name: string;
  width: number;
  height: number;
  created_at: string;
}

export interface MapJobItem {
  job: Job;
  facts: Fact[];
  checklist: RequirementStatus[] | null;
  pin: JobPin | null;
  status: PinStatus | null;
  status_error: string | null;
}

export interface SiteMapState {
  plan: SitePlan | null;
  jobs: MapJobItem[];
}

export type AskTurnKind = "job" | "general" | "greeting" | "clarification";
export type AskItemKind = "missing_information" | "from_record" | "message";

export interface AskHistoryMessage {
  role: "user" | "assistant";
  text: string;
}

export interface AskItem {
  text: string;
  kind: AskItemKind;
  source_ids: number[];
  fact_ids: number[];
  requirement_ids: string[];
  related_fact_ids: number[];
}

export interface AskAnswer {
  job_id: number;
  question: string;
  kind: AskTurnKind;
  items: AskItem[];
  truncated: boolean;
  model: string;
  wall_ms: number | null;
}

export interface Source {
  id: number;
  job_id: number;
  kind: SourceKind;
  text: string;
  created_at: string;
  audio_path: string | null;
  photo_path: string | null;
  segments: Segment[] | null;
  answers_requirement: string | null;
  revises: number | null;
  replaced_by: number | null;
  original_transcript: string | null;
  transcription_ms: number | null;
  extraction_ms: number | null;
}

export interface Fact {
  id: number;
  source_id: number;
  field: FieldName;
  item: string | null;
  value: string | null;
  state: FactState;
  quote: string;
  quote_start: number;
  quote_end: number;
  corrected_from: string | null;
  supersedes: number | null;
  superseded_by: number | null;
  review_status: ReviewStatus;
  conflict_group: number | null;
  invalidated: boolean;
  active: boolean;
  note: string | null;
  created_at: string;
}

export interface Rejection {
  source_id: number;
  proposal: Record<string, unknown>;
  reason: string;
}

export interface RunInfo {
  id: number;
  source_id: number;
  model: string;
  ok: boolean;
  error: string | null;
  wall_ms: number | null;
  total_ms: number | null;
  load_ms: number | null;
  prompt_tokens: number | null;
  eval_tokens: number | null;
  eval_ms: number | null;
  created_at: string;
}

export interface RequirementStatus {
  id: string;
  section: string;
  label: string;
  status: RequirementState;
  satisfied: boolean;
  detail: string;
  fact_ids: number[];
}

export interface Question {
  requirement_id: string;
  text: string;
  fact_ids: number[];
}

export interface Readiness {
  ready: boolean;
  summary: string;
  disclaimer: string;
}

export interface JobState {
  job: Job;
  procedure_title: string;
  sources: Source[];
  facts: Fact[];
  checklist: RequirementStatus[];
  next_question: Question | null;
  readiness: Readiness;
  last_run: RunInfo | null;
  rejected: Rejection[];
}

export interface Health {
  ollama_reachable: boolean;
  model: string;
  model_installed: boolean;
  quantization: string | null;
  parameter_size: string | null;
  device: string;
  ffmpeg_available: boolean;
  whisper_available: boolean;
  whisper_model: string;
  error: string | null;
}

export interface TranscribeOut {
  text: string;
  segments: Segment[];
  audio_path: string;
  duration_ms: number;
  peak_db: number | null;
  convert_ms: number;
  whisper_ms: number;
  wall_ms: number;
  model: string;
}
