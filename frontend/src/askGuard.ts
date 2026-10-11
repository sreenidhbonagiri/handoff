import type { Fact, RequirementStatus } from "./types";

export function isStaleAsk(wantedJobId: number, answerJobId: number, gen: number, currentGen: number): boolean {
  return wantedJobId !== answerJobId || gen !== currentGen;
}

export function factCiteLabel(fact: { superseded_by: number | null; review_status: string }): string | null {
  if (fact.superseded_by != null) return "Earlier value";
  if (fact.review_status === "needs_review" || fact.review_status === "conflicting") return "Awaiting confirmation";
  return null;
}

export const ASK_MISSING_TITLE: Record<string, string> = {
  R1: "Equipment ID",
  R2: "Work done and parts used",
  R3: "Final equipment test",
  R4: "Remaining problem status",
  R5: "Follow-up work",
};

export function missingInformationText(requirementIds: string[], checklist: RequirementStatus[]): string {
  const byId = new Map(checklist.map((r) => [r.id, r]));
  return requirementIds
    .map((id) => {
      const req = byId.get(id);
      if (!req || req.status !== "not_recorded") return null;
      const title = ASK_MISSING_TITLE[id] ?? "Checklist item";
      return `${title}: not recorded.`;
    })
    .filter((line): line is string => Boolean(line))
    .join(" ");
}

export function relatedOpenIssueCaption(fact: Fact): string | null {
  if (fact.field !== "issue" || fact.state !== "unresolved") return null;
  if (fact.review_status !== "accepted" && fact.review_status !== "confirmed") return null;
  const item = (fact.item || "").trim();
  return item ? `Current record: ${item} still open.` : "Current record: still open.";
}
