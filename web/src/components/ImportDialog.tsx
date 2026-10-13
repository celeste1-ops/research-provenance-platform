import { useState } from "react";
import { api, getSpace, tableTemplateUrl } from "../api";
import { dev, isWindows } from "../device";
import { t, tn } from "../i18n";
import { typeLabel } from "../labels";
import type { NotesPreview, Project, TablePreview } from "../types";

// Bringing earlier material in (DECISIONS D-060): a folder of Markdown notes (an Obsidian vault,
// or any folder of .md files), or a table (CSV). Each note or row becomes a step; its date is
// kept as the author's own statement, never as a verified time.

type Tab = "notes" | "table";

function Confirm({ count, onYes, onNo, busy }: { count: number; onYes: () => void; onNo: () => void; busy: boolean }) {
  return (
    <div className="status-box warning-box" data-testid="import-confirm">
      <p>
        {tn(count, "{n} step will be added to My research. It can't be changed or deleted afterwards — later you can add to it.",
          "{n} steps will be added to My research. They can't be changed or deleted afterwards — later you can add to them.")}
      </p>
      <div className="actions start">
        <button className="secondary" onClick={onNo}>{t("Go back")}</button>
        <button className="primary" onClick={onYes} disabled={busy} data-testid="import-confirm-yes">
          {busy ? t("Importing…") : t("Save to my record")}
        </button>
      </div>
    </div>
  );
}

function NotesTab({ project, onImported }: { project: string; onImported: (n: number) => void }) {
  const [path, setPath] = useState("");
  const [info, setInfo] = useState<NotesPreview | null>(null);
  const [skip, setSkip] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function look(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const i = await api.importNotesInspect(path);
      setInfo(i);
      setPath(i.folder);
      setSkip(new Set());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const chosen = info ? info.notes.filter((n) => !skip.has(n.rel)) : [];

  async function run() {
    if (!info) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.importNotes(info.folder, project, skip.size ? chosen.map((n) => n.rel) : null);
      onImported(out.imported);
    } catch (err) {
      setError((err as Error).message);
      setAsking(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="import-notes">
      <form onSubmit={look} className="row">
        <input value={path} onChange={(e) => { setPath(e.target.value); setInfo(null); }}
          placeholder={isWindows() ? "C:\\Users\\you\\Documents\\Obsidian\\FSF" : "/Users/you/Documents/Obsidian/FSF"}
          aria-label={t("Notes folder")} data-testid="import-notes-path" />
        <button className="secondary" disabled={busy || !path.trim()} data-testid="import-notes-look">{t("Look")}</button>
      </form>
      <p className="note">
        {t("A folder on this {device} with Markdown notes (.md) — an Obsidian vault, for example. Each note becomes a step, oldest first; links between notes ([[…]]) become “builds on”, and pictures a note shows are attached.", { device: dev() })}
      </p>
      {error && <p className="error">{error}</p>}
      {info && (
        <>
          <p>
            {tn(info.count, "{n} note", "{n} notes")}{" · "}
            {t("{n} with a date in the note itself; the others use the file's date.", { n: info.dated })}
          </p>
          <div className="import-list">
            <table className="export-table" data-testid="import-notes-list">
              <thead>
                <tr><th /><th>{t("Note")}</th><th>{t("Date (your statement)")}</th><th>{t("Links")}</th><th>{t("Pictures")}</th></tr>
              </thead>
              <tbody>
                {info.notes.map((n) => (
                  <tr key={n.rel}>
                    <td>
                      <input type="checkbox" checked={!skip.has(n.rel)} aria-label={n.title} onChange={(e) => {
                        const next = new Set(skip);
                        if (e.target.checked) next.delete(n.rel);
                        else next.add(n.rel);
                        setSkip(next);
                      }} />
                    </td>
                    <td>{n.title}<div className="muted small mono">{n.rel}</div></td>
                    <td className="small">
                      {n.date ?? "—"}
                      <div className="muted">{n.date_source === "front matter" ? t("from the note") : t("file date")}</div>
                    </td>
                    <td className="small">{n.links || ""}</td>
                    <td className="small">{n.images || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note">
            {t("These dates are your own statement: the date stamps show the day the notes were added. A file's date changes when the file is copied or saved again, so a date written in the note (date: in its front matter) is better.")}
          </p>
          {asking ? (
            <Confirm count={chosen.length} onYes={run} onNo={() => setAsking(false)} busy={busy} />
          ) : (
            <div className="actions start">
              <button className="primary" disabled={busy || !chosen.length || !project} data-testid="import-notes-go"
                onClick={() => (getSpace() === "real" ? setAsking(true) : void run())}>
                {tn(chosen.length, "Import {n} note", "Import {n} notes")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TableTab({ project, onImported }: { project: string; onImported: (n: number) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [info, setInfo] = useState<TablePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(f: File | null) {
    setFile(f);
    setInfo(null);
    setError(null);
    if (!f) return;
    setBusy(true);
    try {
      setInfo(await api.importTableInspect(f));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onImported((await api.importTable(file, project)).imported);
    } catch (err) {
      setError((err as Error).message);
      setAsking(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="import-table">
      <p className="note">
        {t("A table saved as CSV (Excel: File → Save As → CSV UTF-8). One row per step; the column title is needed, and date, type, text, builds on (row numbers) and key step are read when present.")}{" "}
        <a href={tableTemplateUrl()} download data-testid="import-template">{t("Download an example table")}</a>
      </p>
      <input type="file" accept=".csv,.tsv,.txt,text/csv" onChange={(e) => void choose(e.target.files?.[0] ?? null)}
        aria-label={t("Table file")} data-testid="import-table-file" />
      {error && <p className="error">{error}</p>}
      {info && (
        <>
          <div className="import-list">
            <table className="export-table" data-testid="import-table-list">
              <thead>
                <tr><th>#</th><th>{t("Title")}</th><th>{t("Type")}</th><th>{t("Date (your statement)")}</th><th>{t("Builds on")}</th><th /></tr>
              </thead>
              <tbody>
                {info.rows.map((r) => (
                  <tr key={r.number} className={r.title ? "" : "muted"}>
                    <td>{r.number}</td>
                    <td>
                      {r.title || "—"}{r.key && <span className="key-tag"> ★</span>}
                      {r.problems.map((p) => <div key={p} className="warning small">{p}</div>)}
                    </td>
                    <td className="small">{typeLabel(r.type)}</td>
                    <td className="small">{r.date ?? ""}</td>
                    <td className="small">{r.builds_on.map((n) => `#${n}`).join(" ")}</td>
                    <td />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {asking ? (
            <Confirm count={info.count} onYes={run} onNo={() => setAsking(false)} busy={busy} />
          ) : (
            <div className="actions start">
              <button className="primary" disabled={busy || !info.count || !project} data-testid="import-table-go"
                onClick={() => (getSpace() === "real" ? setAsking(true) : void run())}>
                {tn(info.count, "Import {n} row", "Import {n} rows")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function ImportDialog({ projects, projectId, onClose, onImported, onGit }: {
  projects: Project[];
  projectId: string;
  onClose: () => void;
  onImported: () => void;
  onGit: () => void;
}) {
  const [tab, setTab] = useState<Tab>("notes");
  const [project, setProject] = useState(projectId || projects[0]?.id || "");
  const [done, setDone] = useState<number | null>(null);

  function imported(n: number) {
    setDone(n);
    onImported();
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Import")}>
      <div className="modal wide" data-testid="import-dialog">
        <div className="modal-head">
          <h2>{t("Import earlier material")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <div className="segmented small" role="tablist" aria-label={t("Import")}>
          <button role="tab" aria-selected={tab === "notes"} className={tab === "notes" ? "on" : ""} onClick={() => setTab("notes")}
            data-testid="import-tab-notes">
            {t("Notes folder (Markdown, Obsidian)")}
          </button>
          <button role="tab" aria-selected={tab === "table"} className={tab === "table" ? "on" : ""} onClick={() => setTab("table")}
            data-testid="import-tab-table">
            {t("Table (CSV, Excel)")}
          </button>
          <button role="tab" aria-selected={false} onClick={onGit} data-testid="import-tab-git">
            {t("Code (git, GitHub)…")}
          </button>
        </div>
        {projects.length > 1 && (
          <label>
            {t("Into project")}
            <select value={project} onChange={(e) => setProject(e.target.value)} data-testid="import-project">
              {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </select>
          </label>
        )}
        {done !== null ? (
          <div className="status-box" data-testid="import-done">
            <p>{tn(done, "{n} step added. Its date stamp follows in a few minutes.", "{n} steps added. Their date stamps follow in a few minutes.")}</p>
            <div className="actions start">
              <button className="primary" onClick={onClose}>{t("Done")}</button>
            </div>
          </div>
        ) : tab === "notes" ? (
          <NotesTab project={project} onImported={imported} />
        ) : (
          <TableTab project={project} onImported={imported} />
        )}
      </div>
    </div>
  );
}
