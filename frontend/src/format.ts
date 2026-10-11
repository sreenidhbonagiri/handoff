import { countedAsset } from "./closeout";
import type { Fact, FactState, JobState, RequirementStatus, RequirementState, ReviewStatus } from "./types";

export const STATE_LABEL: Record<FactState, string> = {
  reported_complete: "Reported done",
  planned: "Planned",
  explicitly_not_complete: "Not done yet",
  unresolved: "Still open",
  resolved: "Reported fixed",
  observed: "Recorded",
};

export const REQUIREMENT_LABEL: Record<RequirementState, string> = {
  reported: "Recorded",
  planned: "Planned",
  not_recorded: "Not recorded",
  not_complete: "Not done yet",
  conflicting: "Notes disagree",
  unresolved: "Still open",
  not_applicable: "Not needed",
};

export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  accepted: "Recorded",
  conflicting: "Notes disagree",
  needs_review: "Please review",
  confirmed: "Confirmed",
};

export const PENDING_LABEL = "Please review";

export const CHECKLIST_TITLE: Record<string, string> = {
  R1: "Equipment ID",
  R2: "Work done and parts used",
  R3: "Final equipment test",
  R4: "Problems still open",
  R5: "Follow-up work",
};

export const FIELD_LABEL: Record<Fact["field"], string> = {
  asset_id: "Equipment",
  part_replaced: "Parts",
  final_test: "Final equipment test",
  issue: "Problems",
  follow_up: "Follow-up",
  other_action: "Other work",
};

const ATTENTION_STATES = new Set<FactState>(["planned", "explicitly_not_complete", "unresolved"]);
const TARGET_IGNORED = /target_fact_id \d+ ignored \(not an active \w+ fact\)/i;
const VALUE_FROM_WORDS = /^value .+ taken from the words after /i;
const REPEAT_VALUE = "the corrected value repeats the value being corrected; confirm the quantity";
const CAPTION_NOTE = "from the technician's caption, not from visual analysis of the photo";
const ANSWER_HELPER = "Your answer will be added to the job notes.";

export function describe(f: Fact): string {
  const item = f.item ?? "";
  switch (f.field) {
    case "asset_id":
      return `Equipment ID ${f.value ?? "?"}`;
    case "part_replaced":
      return f.value ? `Replace ${f.value} \u00d7 ${item}` : `Replace ${item} (quantity not recorded)`;
    case "final_test":
      return "Final equipment test" + (f.value ? `: ${f.value}` : "");
    case "issue":
      return `Problem: ${item}`;
    case "follow_up":
      return `Follow-up: ${item || "recorded"}`;
    default:
      return item || "Action";
  }
}

export function isPending(f: Fact): boolean {
  return f.review_status === "needs_review" || f.review_status === "conflicting";
}

export function testResultLabel(value: string | null | undefined): "Passed" | "Failed" | null {
  const v = (value ?? "").toLowerCase();
  if (/\bfail/.test(v)) return "Failed";
  if (/\bpass/.test(v) || v === "ok") return "Passed";
  return null;
}

export function badgeClass(f: Fact): string {
  if (f.review_status === "needs_review") return "pending";
  if (f.review_status === "conflicting") return "conflict";
  if (f.field === "final_test" && f.state === "reported_complete") {
    return testResultLabel(f.value) === "Failed" ? "explicitly_not_complete" : "reported_complete";
  }
  return f.state;
}

export function displayState(f: Fact): string {
  if (f.review_status === "needs_review") return REVIEW_LABEL.needs_review;
  if (f.review_status === "conflicting") return REVIEW_LABEL.conflicting;
  if (f.field === "asset_id") return "Recorded";
  if (f.field === "final_test" && f.state === "reported_complete") {
    return testResultLabel(f.value) ?? "Recorded";
  }
  return STATE_LABEL[f.state];
}

export function proposedChange(f: Fact, job: JobState): string {
  const next = `${describe(f)} (${displayState({ ...f, review_status: "accepted" })})`;
  if (f.supersedes !== null) {
    const target = job.facts.find((x) => x.id === f.supersedes);
    if (target) {
      return `If you confirm, this will replace “${describe(target)}” (${displayState(target)}) with “${describe(f)}” (${STATE_LABEL[f.state]}).`;
    }
    return `If you confirm, this will record ${next}. The earlier item it refers to is no longer available.`;
  }
  if (f.review_status === "conflicting") {
    return `If you confirm, this note will be treated as the correct one: ${next}.`;
  }
  return `If you confirm, this will be recorded as ${next}.`;
}

export function replacementTarget(f: Fact, job: JobState): Fact | null {
  if (f.supersedes === null) return null;
  return job.facts.find((x) => x.id === f.supersedes) ?? null;
}

export function ambiguousIssueResolution(f: Fact, job: JobState): boolean {
  return (
    f.review_status === "needs_review" &&
    f.supersedes === null &&
    f.field === "issue" &&
    f.state === "resolved" &&
    job.facts.filter((x) => x.active && x.field === "issue" && x.state === "unresolved" && x.id !== f.id).length > 1
  );
}

export function groupActiveFacts(facts: Fact[]): { review: Fact[]; attention: Fact[]; recorded: Fact[] } {
  const active = facts.filter((f) => f.active);
  return {
    review: active.filter(isPending),
    attention: active.filter((f) => !isPending(f) && ATTENTION_STATES.has(f.state)),
    recorded: active.filter((f) => !isPending(f) && !ATTENTION_STATES.has(f.state)),
  };
}

export function friendlyDiagnostics(note: string | null): { helpful: string[]; raw: string | null } {
  if (!note) return { helpful: [], raw: null };
  const helpful: string[] = [];
  const raw: string[] = [];
  for (const part of note.split("; ").map((p) => p.trim()).filter(Boolean)) {
    if (TARGET_IGNORED.test(part)) {
      helpful.push("This note could not be matched to an existing item automatically. Please confirm what it refers to.");
      raw.push(part);
    } else if (part === REPEAT_VALUE) {
      helpful.push("The quantity in this note is unclear. Please confirm the number.");
      raw.push(part);
    } else if (part === CAPTION_NOTE) {
      helpful.push("Taken from the photo caption. The photo itself was not analyzed.");
    } else if (VALUE_FROM_WORDS.test(part)) {
      raw.push(part);
    } else if (part.endsWith("?")) {
      helpful.push(part);
    } else {
      raw.push(part);
    }
  }
  return { helpful, raw: raw.length ? raw.join("; ") : null };
}

export function sourceKindLabel(kind: string): string {
  switch (kind) {
    case "voice":
      return "Voice note";
    case "photo":
      return "Photo";
    case "answer":
      return "Answer";
    case "review":
      return "Review";
    default:
      return "Note";
  }
}

export function checklistTitle(id: string, fallback = ""): string {
  return CHECKLIST_TITLE[id] ?? fallback.replace(/^§?\d+\s*/, "");
}

export function requirementBadge(r: RequirementStatus, job: JobState): { text: string; className: string } {
  if (r.status === "conflicting") {
    const held = r.fact_ids.some((id) => job.facts.find((f) => f.id === id)?.review_status === "needs_review");
    return held
      ? { text: REVIEW_LABEL.needs_review, className: "pending" }
      : { text: REVIEW_LABEL.conflicting, className: "conflicting" };
  }
  if (r.status === "reported" && r.id === "R3") {
    const test = job.facts.find((f) => f.active && f.field === "final_test" && !isPending(f));
    const result = testResultLabel(test?.value);
    if (result === "Failed") return { text: "Failed", className: "not_complete" };
    if (result === "Passed") return { text: "Passed", className: "reported" };
    return { text: "Recorded", className: "reported" };
  }
  if (r.status === "reported" && r.id === "R2") return { text: "Reported done", className: "reported" };
  if (r.status === "reported") return { text: "Recorded", className: "reported" };
  return { text: REQUIREMENT_LABEL[r.status], className: r.status };
}

export function checklistDetail(r: RequirementStatus, job: JobState): string {
  const pending = r.status === "conflicting";
  switch (r.id) {
    case "R1": {
      const asset = job.facts.find((f) => f.active && f.field === "asset_id" && !isPending(f));
      if (asset?.value && !pending) return `Equipment ID: ${asset.value}`;
      if (pending) return "The equipment ID still needs your review.";
      return "No equipment ID recorded yet.";
    }
    case "R2": {
      if (r.status === "reported") return "Completed work is recorded.";
      if (r.status === "planned") return "Work is planned. It is not recorded as done.";
      if (r.status === "not_complete") return "Work was reported as not done yet.";
      if (pending) return "Notes about the work still need your review.";
      return "No completed work recorded yet.";
    }
    case "R3": {
      if (r.status === "reported") {
        const test = job.facts.find((f) => f.active && f.field === "final_test" && !isPending(f));
        const result = testResultLabel(test?.value);
        if (result) return `Final equipment test: ${result.toLowerCase()}.`;
        return test?.value ? `Final equipment test: ${test.value}.` : "A test result is recorded.";
      }
      if (r.status === "planned") return "The final equipment test is planned. No result is recorded yet.";
      if (r.status === "not_complete") return "The final equipment test was reported as not done yet.";
      if (pending) return "Notes about the final equipment test still need your review.";
      return "No test result recorded yet.";
    }
    case "R4": {
      if (r.status === "unresolved") {
        const names = job.facts
          .filter((f) => f.active && f.field === "issue" && f.state === "unresolved" && !isPending(f))
          .map((f) => f.item)
          .filter((name): name is string => !!name);
        return names.length ? `Still open: ${names.join(", ")}.` : "A problem is still open.";
      }
      if (r.status === "reported") return "No problems are recorded as still open.";
      if (pending) return "Notes about remaining problems still need your review.";
      return "No update on remaining problems yet.";
    }
    case "R5": {
      if (r.status === "not_applicable") return "No follow-up is needed.";
      if (r.status === "reported") {
        const follow = job.facts.find((f) => f.active && f.field === "follow_up" && !isPending(f));
        return follow ? `Follow-up: ${follow.item || follow.quote}.` : "A follow-up plan is recorded.";
      }
      if (pending) return "Notes about follow-up still need your review.";
      return "No follow-up plan recorded yet.";
    }
    default:
      return r.detail;
  }
}

export function hasJobNotes(job: JobState): boolean {
  return job.sources.some((s) => s.replaced_by === null);
}

export function equipmentLine(job: Pick<JobState, "facts">): string {
  const asset = job.facts.find((f) => f.active && f.field === "asset_id" && !isPending(f));
  return asset?.value ? `Equipment ${asset.value}` : "No equipment ID recorded yet.";
}

export function jobTitle(title: string | null | undefined): string {
  const text = (title ?? "").trim();
  return text || "Untitled service visit";
}

export function jobLocation(location: string | null | undefined): string {
  const text = (location ?? "").trim();
  return text || "Location not added";
}

export function equipmentLabel(job: Pick<JobState, "facts">): string {
  return countedAsset(job)?.value?.trim() || "Equipment not recorded";
}

export function compactMissing(value: string | null | undefined): string {
  return (value ?? "").trim() || "Not added";
}

export function compactEquipment(job: Pick<JobState, "facts">): string {
  return compactMissing(countedAsset(job)?.value);
}

export interface FollowUpCopy {
  reason: string;
  question: string;
  placeholder: string;
  helper: string;
}

function placeholderFor(requirementId: string, kind: "missing" | "ambiguous" | "conflict"): string {
  if (kind === "conflict") return "For example: say which note is right.";
  if (kind === "ambiguous") {
    if (requirementId === "R3") return "For example: ‘The final equipment test passed’ or ‘I meant the pressure test.’";
    return "For example: say what was done, and whether it is finished.";
  }
  switch (requirementId) {
    case "R1":
      return "For example: ‘RT-9’ or ‘I can’t read the label yet.’";
    case "R2":
      return "For example: ‘Replaced one contactor’ or ‘The work isn’t finished yet.’";
    case "R3":
      return "For example: ‘It passed’ or ‘I haven’t tested it yet.’";
    case "R4":
      return "For example: ‘The leak is still there’ or ‘The leak is gone.’";
    case "R5":
      return "For example: ‘Return tomorrow with a new gasket.’";
    default:
      return "For example: ‘It passed’ or ‘I haven’t tested it yet.’";
  }
}

function missingQuestion(r: RequirementStatus | undefined, cited: Fact[]): string {
  const id = r?.id;
  if (id === "R1") return "What equipment ID is printed on the unit’s label?";
  if (id === "R2") {
    if (r?.detail.toLowerCase().includes("quantity") && cited.length) {
      const names = cited.map((f) => f.item || "part").join(", ");
      return `How many were replaced (${names})?`;
    }
    return "What work was completed, and which parts and quantities were used?";
  }
  if (id === "R3") {
    if (r?.status === "planned") {
      return "The notes say the final equipment test is planned. Has it been done? If so, did it pass or fail?";
    }
    if (r?.status === "not_complete") {
      return "The notes say the final equipment test was not done. Has it been done since? If so, did it pass or fail?";
    }
    if (cited.length) return "The final equipment test was mentioned. Did it pass or fail?";
    return "Did you run the final equipment test? If so, did it pass or fail?";
  }
  if (id === "R4") return "Are any problems still present, or were they all resolved?";
  if (id === "R5") {
    const problem = cited[0]?.item;
    return problem
      ? `What follow-up is planned for the open problem (${problem})?`
      : "What follow-up is planned for the open problem?";
  }
  return "Can you add a little more detail in your own words?";
}

export function followUpCopy(job: JobState): FollowUpCopy | null {
  const q = job.next_question;
  if (!q) return null;
  const req = job.checklist.find((r) => r.id === q.requirement_id);
  const cited = q.fact_ids
    .map((id) => job.facts.find((f) => f.id === id))
    .filter((f): f is Fact => !!f);
  const held = cited.filter((f) => f.review_status === "needs_review");
  const unsettled = cited.filter((f) => f.review_status !== "accepted" && f.review_status !== "confirmed");

  let kind: "missing" | "ambiguous" | "conflict" = "missing";
  if (req?.status === "conflicting") {
    kind = held.length > 0 && held.length === unsettled.length ? "ambiguous" : "conflict";
  }

  if (kind === "conflict") {
    const quotes = cited.map((f) => `“${f.quote}”`).join(" or ");
    return {
      reason: "These notes disagree. Which is correct?",
      question: quotes ? `The notes say ${quotes}.` : "Which note is correct?",
      placeholder: placeholderFor(q.requirement_id, "conflict"),
      helper: ANSWER_HELPER,
    };
  }

  if (kind === "ambiguous") {
    const noteQ = (held[0]?.note || "").split("; ").find((part) => part.endsWith("?"));
    const ask = noteQ ? `${noteQ[0].toUpperCase()}${noteQ.slice(1)}` : "What exactly was done, and is it finished?";
    const quote = held[0]?.quote;
    return {
      reason: "We need a little more detail to update the job.",
      question: quote ? `Your note says “${quote}”. ${ask}` : ask,
      placeholder: placeholderFor(q.requirement_id, "ambiguous"),
      helper: ANSWER_HELPER,
    };
  }

  return {
    reason: "Your notes don’t include this yet.",
    question: missingQuestion(req, cited),
    placeholder: placeholderFor(q.requirement_id, "missing"),
    helper: ANSWER_HELPER,
  };
}
