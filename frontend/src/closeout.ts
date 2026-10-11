import type { Fact, JobState, RequirementStatus } from "./types";

const PENDING = new Set(["needs_review", "conflicting"]);
const OPEN_CHECK = new Set(["not_recorded", "planned", "not_complete"]);

export function pendingFacts(job: Pick<JobState, "facts">): Fact[] {
  return job.facts.filter((f) => f.active && PENDING.has(f.review_status));
}

export function openChecks(job: Pick<JobState, "checklist">): RequirementStatus[] {
  return job.checklist.filter((r) => OPEN_CHECK.has(r.status));
}

export type PinStatus = "open_problem" | "needs_attention" | "no_open_items";

export function pinStatus(job: Pick<JobState, "facts" | "checklist">): PinStatus {
  if (unresolvedIssues(job).length > 0) return "open_problem";
  if (pendingFacts(job).length > 0 || openChecks(job).length > 0) return "needs_attention";
  return "no_open_items";
}

export function unresolvedIssues(job: Pick<JobState, "facts">): Fact[] {
  return job.facts.filter((f) => f.active && f.field === "issue" && f.state === "unresolved");
}

export function completedWork(job: JobState): Fact[] {
  return job.facts.filter(
    (f) => f.active && f.state === "reported_complete" && !PENDING.has(f.review_status),
  );
}

export function countedAsset(job: Pick<JobState, "facts">): Fact | null {
  return (
    job.facts.find((f) => f.active && f.field === "asset_id" && !PENDING.has(f.review_status)) ?? null
  );
}

export function attachedPhotos(job: JobState) {
  return job.sources.filter((s) => s.photo_path && s.replaced_by === null);
}

export function canPrepareCompleted(job: JobState): boolean {
  return job.readiness.ready && pendingFacts(job).length === 0;
}

export function workRemains(job: JobState): boolean {
  return (
    !job.readiness.ready ||
    pendingFacts(job).length > 0 ||
    unresolvedIssues(job).length > 0 ||
    openChecks(job).length > 0
  );
}

export function closeoutHeadline(job: JobState): string {
  if (canPrepareCompleted(job) && !workRemains(job)) return "Recorded work looks complete.";
  if (pendingFacts(job).length > 0) return "Some items need your review.";
  if (unresolvedIssues(job).length > 0 || openChecks(job).length > 0) {
    return "Some work still needs attention.";
  }
  return "Review the recorded work before you leave.";
}
