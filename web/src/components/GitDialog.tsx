import { useCallback, useEffect, useRef, useState } from "react";
import { api, getSpace } from "../api";
import { dev, isWindows } from "../device";
import { t, tn, tx } from "../i18n";
import type { GitInspect, GitSource, GitStatus, Project } from "../types";
import { timeAgo } from "../util";

// Recording a git repository (DECISIONS D-047): every new commit on one branch becomes a code
// step. Only the repository on this computer is read; nothing is fetched or pushed.

function SourceRow({ s, onRemove }: { s: GitSource; onRemove: (s: GitSource) => void }) {
  return (
    <tr data-testid={`git-source-${s.name}`}>
      <td>
        <b>{s.name}</b> <span className="muted">({s.branch})</span>
        <div className="muted small mono">{s.path}</div>
      </td>
      <td>{s.project_title}</td>
      <td>
        {s.busy ? (
          <span data-testid="git-busy">
            {s.busy.total
              ? t("Recording… {done} of {total}", { done: s.busy.done, total: s.busy.total })
              : t("Starting…")}
          </span>
        ) : (
          <span data-testid="git-recorded">{tn(s.recorded, "{n} step recorded", "{n} steps recorded")}</span>
        )}
        {s.checked && <div className="muted small">{t("Last looked: {when}", { when: timeAgo(s.checked) })}</div>}
        {s.error && <div className="error small">{s.error}</div>}
      </td>
      <td>
        <button className="link small" onClick={() => onRemove(s)} data-testid="git-remove">
          {t("Stop recording")}
        </button>
      </td>
    </tr>
  );
}

function AddForm({ projects, projectId, onAdded }: {
  projects: Project[];
  projectId: string;
  onAdded: (s: GitStatus) => void;
}) {
  const [path, setPath] = useState("");
  const [info, setInfo] = useState<GitInspect | null>(null);
  const [branch, setBranch] = useState("");
  const [project, setProject] = useState(projectId);
  const [history, setHistory] = useState(false);
  const [keepCode, setKeepCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function look(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const i = await api.gitInspect(path);
      setInfo(i);
      setPath(i.path);
      setBranch(i.branch ?? "");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    if (!info) return;
    setBusy(true);
    setError(null);
    try {
      onAdded(await api.gitAdd({ path: info.path, branch, project_id: project, history, keep_code: keepCode }));
      setInfo(null);
      setPath("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const real = getSpace() === "real";
  return (
    <div className="git-add" data-testid="git-add">
      <h3>{t("Record a repository")}</h3>
      <form onSubmit={look} className="row">
        <input value={path} onChange={(e) => { setPath(e.target.value); setInfo(null); }}
          placeholder={isWindows() ? "C:\\Users\\you\\code\\my-project" : "/Users/you/code/my-project"}
          aria-label={t("Repository folder")} data-testid="git-path" />
        <button className="secondary" disabled={busy || !path.trim()} data-testid="git-look">
          {t("Look")}
        </button>
      </form>
      <p className="note">{t("The folder of a git repository on this {device} (the one that contains .git).", { device: dev() })}</p>
      {error && <p className="error">{error}</p>}
      {info && (
        <div className="status-box" data-testid="git-info">
          <p>
            <b>{info.name}</b>{" "}
            {info.commits > 0 && info.first_date
              ? t("— {n} commits from {first} to {last}", { n: info.commits, first: info.first_date, last: info.last_date ?? "" })
              : t("— no commits yet")}
            {info.tags > 0 && t(", {n} tagged", { n: info.tags })}
          </p>
          {info.remote_url && <p className="muted small mono">{info.remote_url}</p>}
          <label>
            {t("Branch")}
            <select value={branch} onChange={(e) => setBranch(e.target.value)} data-testid="git-branch">
              {info.branches.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
          <label>
            {t("Record into project")}
            <select value={project} onChange={(e) => setProject(e.target.value)} data-testid="git-project">
              {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </select>
          </label>
          <fieldset className="choices">
            <label className="check">
              <input type="radio" checked={!history} onChange={() => setHistory(false)} />
              {t("Start from now: the current commit, then every new one")}
            </label>
            <label className="check">
              <input type="radio" checked={history} onChange={() => setHistory(true)} data-testid="git-history" />
              {tn(info.history_steps, "Also add the history so far as {n} step (one per tag or month)",
                "Also add the history so far as {n} steps (one per tag or month)")}
            </label>
            {history && (
              <p className="note">
                {t("History steps are older material added today: the dates git shows are kept as your own statement, not as verified times.")}
              </p>
            )}
          </fieldset>
          <label className="check">
            <input type="checkbox" checked={keepCode} onChange={(e) => setKeepCode(e.target.checked)}
              data-testid="git-keep-code" />
            {t("Keep a copy of the code with each step (zip)")}
          </label>
          <p className="note">
            {keepCode
              ? t("Each step then holds the code itself, so it can still be checked if the repository is deleted or rewritten. This takes space: the whole repository once per commit (up to 50 MB each).")
              : t("Without a copy, a step records which commit it was; the code itself stays only in your repository.")}
          </p>
          {info.already && <p className="error">{t("This branch of this repository is already being recorded.")}</p>}
          {real && (
            <p className="note warning">
              {t("Every commit recorded becomes a permanent step in My research — it can't be changed or deleted.")}
            </p>
          )}
          <div className="actions start">
            <button className="primary" onClick={start} disabled={busy || !branch || !project || info.already}
              data-testid="git-start">
              {t("Start recording")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function GitDialog({ projects, projectId, onClose, onChanged }: {
  projects: Project[];
  projectId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const recorded = useRef<number | null>(null);

  const show = useCallback((s: GitStatus) => {
    setStatus(s);
    const total = s.sources.reduce((n, x) => n + x.recorded, 0);
    if (recorded.current !== null && total !== recorded.current) onChanged();
    recorded.current = total;
  }, [onChanged]);

  useEffect(() => {
    api.gitStatus().then(show).catch((e) => setError((e as Error).message));
  }, [show]);

  // While steps are being saved in the background, show their progress.
  const busy = status?.sources.some((s) => s.busy) ?? false;
  useEffect(() => {
    if (!busy) return;
    const id = window.setInterval(() => {
      api.gitStatus().then(show).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(id);
  }, [busy, show]);

  async function checkNow() {
    setChecking(true);
    setError(null);
    try {
      show(await api.gitCheck());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  async function remove(s: GitSource) {
    if (!window.confirm(t("Stop recording {name}? The steps already recorded stay.", { name: s.name }))) return;
    try {
      show(await api.gitRemove(s.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Record from git")}>
      <div className="modal wide" data-testid="git-dialog">
        <div className="modal-head">
          <h2>{t("Record from git")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <p>
          {t("Every new commit on the branch you choose becomes a code step in your map, with its date stamps — you don't have to add it by hand. The app looks once a minute while it is running, and catches up when it starts again.")}
        </p>
        <p className="note">
          {tx("Only the repository on this {device} is read; nothing is fetched, pushed or sent anywhere (only the fingerprints for the stamps, as for every step). <b>Dates that git shows are your own statement</b>: they can be changed, so they are never shown as verified times.", { b: (s) => <b>{s}</b> }, { device: dev() })}
        </p>
        {error && <p className="error">{error}</p>}
        {status && !status.git && (
          <p className="error" data-testid="git-missing">
            {t("git is not installed on this {device}. Install it from git-scm.com, then open this window again.", { device: dev() })}
          </p>
        )}
        {status && status.sources.length > 0 && (
          <>
            <table className="export-table" data-testid="git-sources">
              <thead>
                <tr>
                  <th>{t("Repository")}</th>
                  <th>{t("Project")}</th>
                  <th>{t("Recorded")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {status.sources.map((s) => <SourceRow key={s.id} s={s} onRemove={remove} />)}
              </tbody>
            </table>
            <div className="actions start">
              <button className="secondary" onClick={checkNow} disabled={checking || busy} data-testid="git-check">
                {checking ? t("Looking…") : t("Look for new commits now")}
              </button>
            </div>
          </>
        )}
        {status?.git && <AddForm projects={projects} projectId={projectId} onAdded={show} />}
      </div>
    </div>
  );
}
