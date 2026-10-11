import type { AskAnswer, AskHistoryMessage, FactState, Health, JobListItem, JobPin, JobState, ObservationIn, SiteMapState, TranscribeOut } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    signal: init?.signal,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // keep statusText
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  listJobs: () => request<JobListItem[]>("/api/jobs"),
  createJob: (title = "", location?: string | null) => post<JobState>("/api/jobs", { title, location: location ?? null }),
  getJob: (id: number) => request<JobState>(`/api/jobs/${id}`),
  updateJob: (id: number, body: { title?: string; location?: string | null }) =>
    request<JobState>(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  addObservation: (id: number, obs: ObservationIn) => post<JobState>(`/api/jobs/${id}/observations`, obs),
  addPhoto: (jobId: number, file: File, caption: string) => {
    const form = new FormData();
    form.append("photo", file, file.name);
    form.append("caption", caption);
    return request<JobState>(`/api/jobs/${jobId}/photos`, { method: "POST", body: form });
  },
  photoUrl: (jobId: number, name: string) => `/api/jobs/${jobId}/photos/${encodeURIComponent(name)}`,
  confirmFact: (jobId: number, factId: number) => post<JobState>(`/api/jobs/${jobId}/facts/${factId}/confirm`),
  reviewFact: (jobId: number, factId: number, value: string | null, state: FactState) =>
    post<JobState>(`/api/jobs/${jobId}/facts/${factId}/review`, { value, state }),
  saveHandoffNote: (jobId: number, note: string) =>
    request<JobState>(`/api/jobs/${jobId}/handoff`, { method: "PATCH", body: JSON.stringify({ note }) }),
  editSource: (sourceId: number, text: string) =>
    request<JobState>(`/api/sources/${sourceId}`, { method: "PATCH", body: JSON.stringify({ text }) }),
  retrySource: (sourceId: number) => post<JobState>(`/api/sources/${sourceId}/extract`),
  transcribe: (blob: Blob) => {
    const form = new FormData();
    form.append("audio", blob, "note.webm");
    return request<TranscribeOut>("/api/transcribe", { method: "POST", body: form });
  },
  // keepalive lets the request finish while the page is closing.
  discardRecording: async (audioPath: string) => {
    const name = audioPath.split("/").pop() ?? "";
    const resp = await fetch(`/api/recordings/${encodeURIComponent(name)}/discard`, { method: "POST", keepalive: true });
    if (!resp.ok && resp.status !== 404) throw new Error(`${resp.status}: could not delete the discarded recording`);
  },
  getSiteMap: () => request<SiteMapState>("/api/site-map"),
  uploadSiteMap: (file: File, name: string, confirmReplace = false) => {
    const form = new FormData();
    form.append("plan", file, file.name);
    form.append("name", name);
    form.append("confirm_replace", confirmReplace ? "true" : "false");
    return request<SiteMapState>("/api/site-map", { method: "POST", body: form });
  },
  siteMapImageUrl: () => `/api/site-map/image?t=${Date.now()}`,
  placePin: (jobId: number, x: number, y: number) => post<JobPin>("/api/site-map/pins", { job_id: jobId, x, y }),
  movePin: (jobId: number, x: number, y: number) =>
    request<JobPin>(`/api/site-map/pins/${jobId}`, { method: "PATCH", body: JSON.stringify({ x, y }) }),
  removePin: (jobId: number) => request<{ removed: boolean }>(`/api/site-map/pins/${jobId}`, { method: "DELETE" }),
  askJob: (id: number, question: string, history: AskHistoryMessage[] = [], signal?: AbortSignal) =>
    request<AskAnswer>(`/api/jobs/${id}/ask`, {
      method: "POST",
      body: JSON.stringify({ question, history }),
      signal,
    }),
  reportHtmlUrl: (id: number, opts?: { mode?: "completed" | "handoff"; note?: string }) =>
    reportUrl(id, "html", opts),
  reportJsonUrl: (id: number, opts?: { mode?: "completed" | "handoff"; note?: string }) =>
    reportUrl(id, "json", opts),
};

function reportUrl(id: number, ext: "html" | "json", opts?: { mode?: "completed" | "handoff"; note?: string }) {
  const q = new URLSearchParams();
  if (opts?.mode) q.set("mode", opts.mode);
  if (opts?.note?.trim()) q.set("note", opts.note.trim());
  const qs = q.toString();
  return `/api/jobs/${id}/report.${ext}${qs ? `?${qs}` : ""}`;
}
