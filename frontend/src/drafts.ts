const flags = new Map<string, boolean>();

export function setDraftDirty(key: string, dirty: boolean): void {
  if (dirty) flags.set(key, true);
  else flags.delete(key);
}

export function hasUnsavedDrafts(): boolean {
  return flags.size > 0;
}

export function clearDrafts(): void {
  flags.clear();
}

export function confirmLeaveJob(): boolean {
  if (!hasUnsavedDrafts()) return true;
  return window.confirm(
    "You have a note, recording, or photo that hasn’t been saved. Leave this job anyway?",
  );
}
