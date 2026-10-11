import { useCallback, useEffect, useState } from "react";
import { api, getSpace } from "../api";
import { dev, isWindows } from "../device";
import { t, tn } from "../i18n";
import { typeLabel } from "../labels";
import type { FolderInspect, InboxItem, InboxStatus, Project } from "../types";
import { timeAgo } from "../util";

// Watched folders and the inbox (DECISIONS D-049). A finished new version of a file waits in the
// inbox with a date stamp of its fingerprint; recording it makes it a step, throwing it away
// leaves nothing behind.

function size(n: number): string {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`;
}

function ItemRow({ item, nodeTypes, onRecord, onDiscard }: {
  item: InboxItem;
  nodeTypes: string[];
  onRecord: (item: InboxItem, title: string, type: string) => Promise<void>;
  onDiscard: (item: InboxItem) => Promise<void>;
}) {
  const [title, setTitle] = useState(item.name);
  const [type, setType] = useState(item.node_type);
  const [busy, setBusy] = useState(false);
  return (
    <li className="inbox-item" data-testid={`inbox-item-${item.name}`}>
      <div className="row">
        <input value={title} onChange={(e) => setTitle(e.target.value)} aria-label={t("Title")} />
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label={t("Type")}>
          {nodeTypes.map((nt) => <option key={nt} value={nt}>{typeLabel(nt)}</option>)}
        </select>
        <button className="primary small" disabled={busy || !title.trim()} data-testid="inbox-record"
          onClick={async () => { setBusy(true); await onRecord(item, title, type); setBusy(false); }}>
          {t("Record as a step")}
        </button>
        <button className="link small" disabled={busy} data-testid="inbox-discard"
          onClick={async () => { setBusy(true); await onDiscard(item); setBusy(false); }}>
          {t("Throw away")}
        </button>
      </div>
      <div className="muted small">
        <span className="mono">{item.folder}/{item.path}</span> · {size(item.size)} · {timeAgo(item.seen)}
        {" · "}
        {item.stamp?.time ? (
          <span data-testid="inbox-stamped">{t("Date stamp ✓ {time}", { time: item.stamp.time })}</span>
        ) : (
          <span className="warning">{t("Date stamp: waiting (the app keeps trying)")}</span>
        )}
        {item.previous && <> · {t("new version of an earlier step")}</>}
      </div>
    </li>
  );
}

export function InboxDialog({ nodeTypes, onClose, onRecorded, onWatch }: {
  nodeTypes: string[];
  onClose: () => void;
  onRecorded: (id: string) => void;
  onWatch: () => void;
}) {
  const [status, setStatus] = useState<InboxStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.inbox().then(setStatus).catch((e) => setError((e as Error).message));
  }, []);
  useEffect(load, [load]);

  async function record(item: InboxItem, title: string, type: string) {
    setError(null);
    try {
      const out = await api.inboxRecord(item.id, { title, node_type: type });
      setStatus(out);
      onRecorded(out.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function discard(item: InboxItem) {
    setError(null);
    try {
      setStatus(await api.inboxDiscard(item.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Inbox")}>
      <div className="modal wide" data-testid="inbox-dialog">
        <div className="modal-head">
          <h2>{t("Inbox")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <p>
          {t("New versions from the folders you watch. Each already has a date stamp of its fingerprint. Record the ones worth keeping — the step keeps that earlier date stamp — and throw the rest away; nothing here is in your record yet.")}
        </p>
        {getSpace() === "real" && (
          <p className="note warning">{t("A recorded version becomes a permanent step in My research.")}</p>
        )}
        {error && <p className="error">{error}</p>}
        {status && status.items.length === 0 && (
          <p className="muted" data-testid="inbox-empty">
            {status.folders.length === 0 ? t("No folder is watched yet.") : t("Nothing new right now.")}
          </p>
        )}
        <ul className="inbox-list">
          {status?.items.map((i) => (
            <ItemRow key={i.id} item={i} nodeTypes={nodeTypes} onRecord={record} onDiscard={discard} />
          ))}
        </ul>
        <div className="actions start">
          <button className="link small" onClick={onWatch}>{t("Watched folders…")}</button>
        </div>
      </div>
    </div>
  );
}

export function FolderDialog({ projects, projectId, onClose }: {
  projects: Project[];
  projectId: string;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<InboxStatus | null>(null);
  const [path, setPath] = useState("");
  const [info, setInfo] = useState<FolderInspect | null>(null);
  const [project, setProject] = useState(projectId);
  const [existing, setExisting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.inbox().then(setStatus).catch((e) => setError((e as Error).message));
  }, []);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Watch a folder")}>
      <div className="modal wide" data-testid="folder-dialog">
        <div className="modal-head">
          <h2>{t("Watch a folder")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <p>
          {t("Pick the folder of a piece of work — drafts, data, figures. When a file there is new or changed and then stays unchanged for two minutes, a copy goes into the inbox with a date stamp of its fingerprint. You decide there what becomes a step.")}
        </p>
        <p className="note">
          {t("Only fingerprints go out, as for every step. Copies stay on this {device}, in the app's data folder, until you record or throw them away. Hidden files, lock and temporary files are skipped, and so are files over 50 MB.", { device: dev() })}
        </p>
        {error && <p className="error">{error}</p>}
        {status && status.folders.length > 0 && (
          <table className="export-table" data-testid="folders">
            <thead>
              <tr><th>{t("Folder")}</th><th>{t("Project")}</th><th>{t("Files")}</th><th /></tr>
            </thead>
            <tbody>
              {status.folders.map((f) => (
                <tr key={f.id} data-testid={`folder-${f.name}`}>
                  <td>
                    <b>{f.name}</b>
                    <div className="muted small mono">{f.path}</div>
                    {f.error && <div className="error small">{f.error}</div>}
                  </td>
                  <td>{f.project_title}</td>
                  <td>
                    {tn(f.files, "{n} file watched", "{n} files watched")}
                    {f.checked && <div className="muted small">{t("Last looked: {when}", { when: timeAgo(f.checked) })}</div>}
                  </td>
                  <td>
                    <button className="link small" disabled={busy}
                      onClick={() => run(async () => {
                        if (window.confirm(t("Stop watching {name}? Versions already in the inbox stay there.", { name: f.name }))) {
                          setStatus(await api.inboxRemoveFolder(f.id));
                        }
                      })}>
                      {t("Stop watching")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="git-add">
          <h3>{t("Watch a new folder")}</h3>
          <form className="row" onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              const i = await api.inboxInspect(path);
              setInfo(i);
              setPath(i.path);
            });
          }}>
            <input value={path} onChange={(e) => { setPath(e.target.value); setInfo(null); }}
              placeholder={isWindows() ? "C:\\Users\\you\\Documents\\paper" : "/Users/you/Documents/paper"}
              aria-label={t("Folder")} data-testid="folder-path" />
            <button className="secondary" disabled={busy || !path.trim()} data-testid="folder-look">{t("Look")}</button>
          </form>
          {info && (
            <div className="status-box" data-testid="folder-info">
              <p>
                <b>{info.name}</b> — {info.too_many
                  ? t("more than {n} files: choose the folder of one piece of work.", { n: info.max_files })
                  : tn(info.files, "{n} file to watch", "{n} files to watch")}
                {info.too_large > 0 && t(" ({n} over 50 MB, skipped)", { n: info.too_large })}
              </p>
              <label>
                {t("Record into project")}
                <select value={project} onChange={(e) => setProject(e.target.value)} data-testid="folder-project">
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                </select>
              </label>
              <label className="check">
                <input type="checkbox" checked={existing} disabled={info.files > info.max_existing}
                  onChange={(e) => setExisting(e.target.checked)} data-testid="folder-existing" />
                {info.files > info.max_existing
                  ? t("Also put the files already there into the inbox (only for up to {n} files)", { n: info.max_existing })
                  : t("Also put the files already there into the inbox")}
              </label>
              {info.already && <p className="error">{t("This folder is already being watched.")}</p>}
              <div className="actions start">
                <button className="primary" disabled={busy || info.too_many || info.already || !project}
                  data-testid="folder-start"
                  onClick={() => run(async () => {
                    setStatus(await api.inboxAddFolder({ path: info.path, project_id: project, include_existing: existing }));
                    setInfo(null);
                    setPath("");
                  })}>
                  {t("Start watching")}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
