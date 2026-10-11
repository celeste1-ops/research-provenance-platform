import type { ExportPreview, Graph, Project, RecordDetail, Status, TimelineRow } from "./types";

// The per-launch session token is embedded in the page by the local server — never in a URL.
function sessionToken(): string {
  const meta = document.querySelector('meta[name="rprov-session-token"]');
  return meta?.getAttribute("content") ?? "";
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
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
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
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
  body: async (id: string) => {
    const res = await fetch(`/api/records/${id}/content`);
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
  verifyAll: () => request<{ ok: boolean; counts: Record<string, number> }>("POST", "/api/verify/all"),
  exportPreview: (body: { title: string; records: Record<string, string>; default: string }) =>
    request<ExportPreview>("POST", "/api/export/preview", body),
  backup: (password: string, location?: string) => backupRequest(password, location),
  restore: (file: File, password: string) => {
    const form = new FormData();
    form.set("file", file, file.name);
    form.set("password", password);
    return request<{ installation: string; records: number; verification: { ok: boolean } }>("POST", "/api/restore", form);
  },
  exportBundle: (body: { title: string; records: Record<string, string>; default: string }) =>
    request<Blob>("POST", "/api/export", body),
};

export async function backupRequest(password: string, location?: string) {
  const res = await fetch("/api/backup", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-RPROV-Token": sessionToken() },
    body: JSON.stringify({ password, location }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  }
  const disposition = res.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "rprov-backup.zip";
  return { blob: await res.blob(), path: res.headers.get("x-backup-path"), filename };
}

export function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
