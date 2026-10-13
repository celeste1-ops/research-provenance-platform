import type {
  AiResult,
  BackupStatus,
  CloudLogEntry,
  CloudPreview,
  CloudProvider,
  CloudStatus,
  BackupSuggestion,
  ExportPreview,
  FolderInspect,
  InboxStatus,
  GitInspect,
  GitStatus,
  Narrative,
  NotesPreview,
  LocationCheck,
  Graph,
  Project,
  RecordDetail,
  RepoExport,
  ServiceCheckResult,
  Status,
  TablePreview,
  TimelineRow,
  Translation,
  ZenodoDraft,
  ZenodoStatus,
} from "./types";
import { lang, t, type Lang } from "./i18n";

// The per-launch session token is embedded in the page by the local server — never in a URL.
function sessionToken(): string {
  const meta = document.querySelector('meta[name="rprov-session-token"]');
  return meta?.getAttribute("content") ?? "";
}

// Which space this page works in (DECISIONS D-038). Every request says so explicitly, so a
// tab always saves where it shows it saves, whatever another tab does.
export type Space = "real" | "practice" | "example";
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
  if (currentSpace !== "real") h["X-RPROV-Space"] = currentSpace;
  return h;
}

type ExportBody = { title: string; records: Record<string, string>; default: string; language?: string };

/** Every step of a project as a table (CSV) — a plain link, so the download is the browser's own. */
function spaceQuery(): string {
  return currentSpace === "real" ? "" : `&space=${currentSpace}`;
}

export function tableUrl(projectId: string): string {
  const space = spaceQuery();
  return `/api/export/table?project=${encodeURIComponent(projectId)}&lang=${lang()}${space}`;
}

export function tableTemplateUrl(): string {
  return `/api/import/table/template?lang=${lang()}`;
}

// For plain links (attachments), which cannot carry a header.
export function contentUrl(id: string, file: string): string {
  const space = spaceQuery();
  // The language too: the example comes in each, and its files are those of the page's (D-065).
  return `/api/records/${id}/content?file=${encodeURIComponent(file)}${space}&lang=${lang()}`;
}

/** An attached image, or the start of a text file, as the app may show it (D-057). */
export function previewUrl(id: string, file: string): string {
  const space = spaceQuery();
  return `/api/records/${id}/preview?file=${encodeURIComponent(file)}${space}&lang=${lang()}`;
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
  body: { url?: string; model: string; project?: string; mode?: "local" | "cloud"; confirm?: string },
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
    if (done) {
      throw new ApiError(502, body.mode === "cloud" ? t("The AI service stopped before it finished.")
        : t("The local model stopped before it finished."));
    }
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
  // A step translated by the model on this computer, never saved (D-066).
  translate: (id: string, lang: string) =>
    request<Translation>("POST", `/api/records/${id}/translation`, { lang }),
  aiSettings: () => request<{ url: string; model: string; cloud: CloudStatus }>("GET", "/api/ai"),
  cloudConnect: (provider: CloudProvider, key: string, url: string) =>
    request<CloudStatus & { models: string[] }>("POST", "/api/ai/cloud", { provider, key, url }),
  cloudForget: () => request<CloudStatus>("DELETE", "/api/ai/cloud"),
  cloudModels: () => request<{ models: string[] }>("POST", "/api/ai/cloud/models"),
  cloudPreview: (model: string, project?: string) =>
    request<CloudPreview>("POST", "/api/ai/cloud/preview", { mode: "cloud", model, project }),
  cloudLog: () => request<{ count: number; entries: CloudLogEntry[] }>("GET", "/api/ai/cloud/log"),
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
  exportToRepository: (body: ExportBody & { path: string; commit: boolean; push: boolean }) =>
    request<RepoExport>("POST", "/api/export/repository", body),
  exportToZenodo: (body: ExportBody) => request<ZenodoDraft>("POST", "/api/export/zenodo", body),
  zenodoStatus: () => request<ZenodoStatus>("GET", "/api/zenodo"),
  zenodoConnect: (token: string, sandbox: boolean) => request<ZenodoStatus>("POST", "/api/zenodo", { token, sandbox }),
  zenodoForget: () => request<ZenodoStatus>("DELETE", "/api/zenodo"),
  importNotesInspect: (path: string) => request<NotesPreview>("POST", "/api/import/notes/inspect", { path }),
  importNotes: (path: string, project_id: string, selected: string[] | null) =>
    request<{ imported: number }>("POST", "/api/import/notes", { path, project_id, selected }),
  importTableInspect: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<TablePreview>("POST", "/api/import/table/inspect", form);
  },
  importTable: (file: File, projectId: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("project_id", projectId);
    return request<{ imported: number }>("POST", "/api/import/table", form);
  },
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
  practiceReset: () => request<{ space: string; record_count: number }>("POST", "/api/practice/reset", {}),
  // The example (D-064): the FSF sample in a space of its own, loaded when first opened.
  exampleOpen: (lang: string) => request<{ space: string; record_count: number }>("POST", "/api/example/open", { lang }),
  exampleReset: (lang: string) => request<{ space: string; record_count: number }>("POST", "/api/example/reset", { lang }),
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
