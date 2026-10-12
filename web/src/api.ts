import type {
  AiResult,
  BackupStatus,
  BackupSuggestion,
  ExportPreview,
  FolderInspect,
  InboxStatus,
  GitInspect,
  GitStatus,
  Narrative,
  LocationCheck,
  Graph,
  Project,
  RecordDetail,
  ServiceCheckResult,
  Status,
  TimelineRow,
} from "./types";
import { lang, t, type Lang } from "./i18n";

// The per-launch session token is embedded in the page by the local server — never in a URL.
function sessionToken(): string {
  const meta = document.querySelector('meta[name="rprov-session-token"]');
  return meta?.getAttribute("content") ?? "";
}

// Which space this page works in (DECISIONS D-038). Every request says so explicitly, so a
// tab always saves where it shows it saves, whatever another tab does.
export type Space = "real" | "practice";
let currentSpace: Space = "real";

export function setSpace(space: Space) {
  currentSpace = space;
}

export function getSpace(): Space {
  return currentSpace;
}

// Every request names the space and the interface language (texts the server writes, D-046).
function spaceHeaders(): Record<string, string> {
  const h: Record<string, string> = { "X-RPROV-Lang": lang() };
  if (currentSpace === "practice") h["X-RPROV-Space"] = "practice";
  return h;
}

// For plain links (attachments), which cannot carry a header.
export function contentUrl(id: string, file: string): string {
  const space = currentSpace === "practice" ? "&space=practice" : "";
  return `/api/records/${id}/content?file=${encodeURIComponent(file)}${space}`;
}

/** An attached image, or the start of a text file, as the app may show it (D-057). */
export function previewUrl(id: string, file: string): string {
  const space = currentSpace === "practice" ? "&space=practice" : "";
  return `/api/records/${id}/preview?file=${encodeURIComponent(file)}${space}`;
}

export async function previewText(id: string, file: string): Promise<{ text: string; truncated: boolean }> {
  const res = await fetch(previewUrl(id, file), { headers: spaceHeaders(), credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return { text: await res.text(), truncated: res.headers.get("X-Preview-Truncated") === "1" };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const KEYCHAIN_DENIED_EVENT = "rprov-keychain-denied";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = spaceHeaders();
  let payload: BodyInit | undefined;
  if (method !== "GET") headers["X-RPROV-Token"] = sessionToken();
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload, credentials: "same-origin" });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      // The keychain refused access: the page shows its "Try again" banner right away.
      if (data.keychain_denied) window.dispatchEvent(new Event(KEYCHAIN_DENIED_EVENT));
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

// The local model's answer arrives as it is written, one JSON object per line: {"text"} pieces,
// then {"result"} (checked) or {"error"}. Aborting the signal stops the model (D-050).
async function aiStoryStream(
  body: { url: string; model: string; project?: string },
  onText: (piece: string) => void,
  signal?: AbortSignal,
): Promise<AiResult> {
  const res = await fetch("/api/ai/story", {
    method: "POST",
    headers: { ...spaceHeaders(), "X-RPROV-Token": sessionToken(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
    signal,
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffered += decoder.decode(value, { stream: !done });
    let end: number;
    while ((end = buffered.indexOf("\n")) >= 0) {
      const line = buffered.slice(0, end).trim();
      buffered = buffered.slice(end + 1);
      if (!line) continue;
      const event = JSON.parse(line) as { text?: string; result?: AiResult; error?: string };
      if (event.text) onText(event.text);
      else if (event.result) return event.result;
      else if (event.error) throw new ApiError(502, event.error);
    }
    if (done) throw new ApiError(502, t("The local model stopped before it finished."));
  }
}

export const api = {
  status: () => request<Status>("GET", "/api/status"),
  createIdentity: (author_label: string) =>
    request<{ genesis: string; reminder: string }>("POST", "/api/identity", { author_label }),
  exportKey: (password: string) => request<Blob>("POST", "/api/identity/export", { password }),
  projects: () => request<Project[]>("GET", "/api/projects"),
  createProject: (title: string) => request<Project>("POST", "/api/projects", { title }),
  renameProject: (id: string, title: string) => request<Project>("POST", `/api/projects/${id}/rename`, { title }),
  graph: (project?: string) =>
    request<Graph>("GET", `/api/graph${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  timeline: (project?: string) =>
    request<TimelineRow[]>("GET", `/api/timeline${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  record: (id: string) => request<RecordDetail>("GET", `/api/records/${id}`),
  aiSettings: () => request<{ url: string; model: string }>("GET", "/api/ai"),
  aiModels: (url: string) => request<{ url: string; models: string[] }>("POST", "/api/ai/models", { url }),
  aiStory: aiStoryStream,
  narrative: (project?: string) =>
    request<Narrative>("GET", `/api/narrative${project ? `?project=${encodeURIComponent(project)}` : ""}`),
  body: async (id: string) => {
    const res = await fetch(`/api/records/${id}/content`, { headers: spaceHeaders() });
    if (!res.ok) throw new ApiError(res.status, "no content");
    return res.text();
  },
  diff: (id: string, against: string) =>
    request<{ body_diff: string; files: Record<string, string[]> }>(
      "GET",
      `/api/records/${id}/diff?against=${encodeURIComponent(against)}`,
    ),
  createEntry: (form: FormData) => request<{ id: string; detail: RecordDetail }>("POST", "/api/entries", form),
  createLink: (body: { from: string; to: string; rel: string; op?: string; statement?: string }) =>
    request<{ id: string }>("POST", "/api/links", body),
  createMilestone: (target: string, op: "set" | "unset") =>
    request<{ id: string }>("POST", "/api/milestones", { target, op }),
  createStatement: (target: string, text: string, corrects?: string) =>
    request<{ id: string }>("POST", "/api/statements", { target, text, corrects }),
  createRetraction: (target: string, reason: string) =>
    request<{ id: string }>("POST", "/api/retractions", { target, reason }),
  refreshAnchors: () => request<Record<string, number>>("POST", "/api/anchors/refresh"),
  networkCheck: () => request<ServiceCheckResult>("POST", "/api/network/check"),
  gitStatus: () => request<GitStatus>("GET", "/api/git"),
  gitInspect: (path: string) => request<GitInspect>("POST", "/api/git/inspect", { path }),
  gitAdd: (body: { path: string; branch: string; project_id: string; history: boolean; keep_code: boolean }) =>
    request<GitStatus>("POST", "/api/git", body),
  gitCheck: () => request<GitStatus & { recorded: number; busy: boolean }>("POST", "/api/git/check"),
  gitRemove: (id: string) => request<GitStatus>("DELETE", `/api/git/${id}`),
  inbox: () => request<InboxStatus>("GET", "/api/inbox"),
  inboxInspect: (path: string) => request<FolderInspect>("POST", "/api/inbox/folders/inspect", { path }),
  inboxAddFolder: (body: { path: string; project_id: string; include_existing: boolean }) =>
    request<InboxStatus>("POST", "/api/inbox/folders", body),
  inboxRemoveFolder: (id: string) => request<InboxStatus>("DELETE", `/api/inbox/folders/${id}`),
  inboxCheck: () => request<InboxStatus & { arrived: number }>("POST", "/api/inbox/check"),
  inboxRecord: (id: string, body: { title: string; node_type: string }) =>
    request<InboxStatus & { id: string }>("POST", `/api/inbox/items/${id}/record`, body),
  inboxDiscard: (id: string) => request<InboxStatus>("DELETE", `/api/inbox/items/${id}`),
  preferences: () => request<{ language: Lang | null }>("GET", "/api/preferences"),
  setPreferences: (prefs: { language: string }) => request<{ language: string }>("POST", "/api/preferences", prefs),
  verifyAll: () => request<{ ok: boolean; counts: Record<string, number> }>("POST", "/api/verify/all"),
  exportPreview: (body: { title: string; records: Record<string, string>; default: string; language?: string }) =>
    request<ExportPreview>("POST", "/api/export/preview", body),
  backupDownload: (password: string) => downloadRequest("/api/backup", { password }),
  backupStatus: () => request<BackupStatus>("GET", "/api/backup/status"),
  keychainRetry: () => request<{ keychain_denied: boolean }>("POST", "/api/keychain/retry"),
  backupSuggestions: () => request<BackupSuggestion[]>("GET", "/api/backup/suggestions"),
  backupSettings: (location: string, password: string, create: boolean) =>
    request<BackupStatus>("POST", "/api/backup/settings", { location, password, create }),
  backupRun: () => request<{ ran: boolean; path: string; status: BackupStatus }>("POST", "/api/backup/run"),
  backupCheck: (location: string) =>
    request<LocationCheck>("GET", `/api/backup/check?location=${encodeURIComponent(location)}`),
  backupResume: () => request<BackupStatus>("POST", "/api/backup/resume"),
  backupAcknowledgeOtherCopy: () => request<BackupStatus>("POST", "/api/backup/other-copy/acknowledge"),
  backupNewRecoveryCode: () =>
    request<{ recovery_code: string; status: BackupStatus }>("POST", "/api/backup/recovery-code"),
  restore: (file: File, secret: { password?: string; recoveryCode?: string }) => {
    const form = new FormData();
    form.set("file", file, file.name);
    if (secret.password) form.set("password", secret.password);
    if (secret.recoveryCode) form.set("recovery_code", secret.recoveryCode);
    return request<{
      installation: string;
      records: number;
      opened_with: string;
      key_fingerprint: string;
      verification: { ok: boolean };
      backup: BackupStatus;
    }>(
      "POST",
      "/api/restore",
      form,
    );
  },
  exportBundle: (body: { title: string; records: Record<string, string>; default: string; language?: string }) =>
    request<Blob>("POST", "/api/export", body),
  practiceReset: (sample: boolean, lang?: string) =>
    request<{ space: string; record_count: number }>("POST", "/api/practice/reset", { sample, lang }),
};

export async function downloadRequest(path: string, body: unknown) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-RPROV-Token": sessionToken(), ...spaceHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  }
  const disposition = res.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
  return { blob: await res.blob(), filename };
}

/** Save a file the page made (an evidence bundle, a key backup, a Markdown text). The browser saves
 * it to Downloads; the app's window (D-058) asks where. The address is kept for a minute, as the
 * window may still be asking when a shorter wait would already have thrown it away. */
export function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
