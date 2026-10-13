import { useEffect, useState } from "react";
import { api, download, tableUrl } from "../api";
import type { ExportPreview, GitSource, RepoExport, TimelineRow, ZenodoDraft, ZenodoStatus } from "../types";
import { lang, t, tx, type Lang } from "../i18n";
import { keychainName } from "../device";

// Where the bundle goes (DECISIONS D-060): a zip to download, a git repository on this computer
// (committed there, pushed to GitHub if asked), or a private draft on Zenodo to publish there.
type Dest = "zip" | "repo" | "zenodo";
type Done = { kind: "repo"; out: RepoExport } | { kind: "zenodo"; out: ZenodoDraft };

const ZENODO_TOKEN_PAGE = {
  live: "https://zenodo.org/account/settings/applications/tokens/new/",
  sandbox: "https://sandbox.zenodo.org/account/settings/applications/tokens/new/",
};

function ZenodoConnect({ onConnected }: { onConnected: (s: ZenodoStatus) => void }) {
  const [token, setToken] = useState("");
  const [sandbox, setSandbox] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function connect() {
    setBusy(true);
    setError(null);
    try {
      onConnected(await api.zenodoConnect(token, sandbox));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="zenodo-connect" data-testid="zenodo-connect">
      <p className="note">
        {tx("Connect Zenodo once with a personal token: on Zenodo, <a>make a new token</a> with the scope <b>deposit:write</b> and paste it here. It is kept in the {keychain} and sent only to Zenodo.",
          { a: (c) => <a href={sandbox ? ZENODO_TOKEN_PAGE.sandbox : ZENODO_TOKEN_PAGE.live} target="_blank" rel="noopener noreferrer">{c}</a>,
            b: (c) => <b>{c}</b> }, { keychain: keychainName() })}
      </p>
      <div className="row">
        <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={t("Zenodo token")}
          aria-label={t("Zenodo token")} data-testid="zenodo-token" autoComplete="off" />
        <button type="button" className="secondary" onClick={connect} disabled={busy || token.trim().length < 10}
          data-testid="zenodo-connect-button">
          {busy ? t("Checking…") : t("Connect")}
        </button>
      </div>
      <label className="check small">
        <input type="checkbox" checked={sandbox} onChange={(e) => setSandbox(e.target.checked)} />
        {t("Use Zenodo's test site (sandbox.zenodo.org) to try it first")}
      </label>
      {error && <p className="error small">{error}</p>}
    </div>
  );
}

type Level = "full" | "structure" | "existence";
const LEVELS: Level[] = ["full", "structure", "existence"];

function levelLabel(l: Level): string {
  return l === "full" ? t("Everything") : l === "structure" ? t("Structure only") : t("Existence only");
}

interface Props {
  rows: TimelineRow[];
  defaultTitle: string;
  onClose: () => void;
  practice?: boolean;
  example?: boolean;
  projectId?: string;
}

export function ExportDialog({ rows, defaultTitle, onClose, practice = false, example = false, projectId = "" }: Props) {
  const entries = rows.filter((r) => r.kind === "entry");
  const [title, setTitle] = useState(defaultTitle);
  const [levels, setLevels] = useState<Record<string, Level>>(() =>
    Object.fromEntries(entries.map((r) => [r.id, "structure" as Level])),
  );
  const [includeAdditions, setIncludeAdditions] = useState(true);
  const [reportLang, setReportLang] = useState<Lang>(lang);
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dest, setDest] = useState<Dest>("zip");
  const [repos, setRepos] = useState<GitSource[]>([]);
  const [repoPath, setRepoPath] = useState("");
  const [push, setPush] = useState(false);
  const [zenodo, setZenodo] = useState<ZenodoStatus | null>(null);
  const [done, setDone] = useState<Done | null>(null);

  useEffect(() => {
    api.gitStatus().then((s) => {
      const local = s.sources.filter((x) => !x.remote);
      setRepos(local);
      if (local[0]) setRepoPath(local[0].path);
    }).catch(() => undefined);
    api.zenodoStatus().then(setZenodo).catch(() => undefined);
  }, []);

  const selection = () => {
    const records: Record<string, string> = { ...levels };
    if (includeAdditions) {
      // Later additions (links, milestones, statements, retractions) travel with structure.
      rows.filter((r) => r.kind !== "entry" && r.kind !== "genesis").forEach((r) => (records[r.id] = "structure"));
    }
    return { title, records, default: "existence", language: reportLang };
  };

  useEffect(() => {
    let live = true;
    api
      .exportPreview(selection())
      .then((p) => live && setPreview(p))
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [levels, includeAdditions, title, reportLang]);

  async function doExport() {
    setBusy(true);
    setError(null);
    try {
      if (dest === "repo") {
        setDone({ kind: "repo", out: await api.exportToRepository({ ...selection(), path: repoPath, commit: true, push }) });
      } else if (dest === "zenodo") {
        setDone({ kind: "zenodo", out: await api.exportToZenodo(selection()) });
      } else {
        const blob = await api.exportBundle(selection());
        const day = new Date().toISOString().slice(0, 10);
        download(blob, `provenance-${title.replace(/[^\p{L}\p{N}._-]+/gu, "-") || "evidence"}-${day}.zip`);
        onClose();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function forgetZenodo() {
    try {
      setZenodo(await api.zenodoForget());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const setAll = (lvl: Level) => setLevels(Object.fromEntries(entries.map((r) => [r.id, lvl])));

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Share")}>
      <div className="modal wide" data-testid="export-dialog">
        <h2>{t("Share")}</h2>
        <p className="small">
          {tx("Makes one zip file to send: a web report, a checking program (<code>verify.py</code>) and step-by-step instructions. The reader needs neither this app nor trust in you.", { code: (c) => <code>{c}</code> })}
        </p>
        {practice && (
          <p className="warning">
            {t("This is practice: the package is signed with the practice key and is not part of your real record.")}
          </p>
        )}
        {example && (
          <p className="warning">
            {t("This is the fictional example: the package is signed with the example's key and is not part of your real record.")}
          </p>
        )}
        <p className="note">
          {t("The report uses the formal names: the date stamp is called “Third-party timestamp” and the public stamp “Bitcoin anchor”.")}
        </p>
        <div className="row">
          <label className="grow">
            {t("Bundle name")}
            <input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label>
            {t("Report language")}
            <select value={reportLang} onChange={(e) => setReportLang(e.target.value as Lang)} data-testid="report-lang">
              <option value="en">English</option>
              <option value="zh">中文</option>
            </select>
          </label>
        </div>
        <div className="row small">
          {t("Set all to:")}
          {LEVELS.map((l) => (
            <button key={l} type="button" className="secondary small" onClick={() => setAll(l)}>
              {levelLabel(l)}
            </button>
          ))}
          <label className="check">
            <input type="checkbox" checked={includeAdditions} onChange={(e) => setIncludeAdditions(e.target.checked)} />
            {t("include later additions")}
          </label>
        </div>
        <table className="export-table">
          <thead>
            <tr>
              <th>#</th>
              <th>{t("Record")}</th>
              <th>{t("Disclose")}</th>
              <th>{t("Will be visible")}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((r) => {
              const p = preview?.records.find((x) => x.id === r.id);
              return (
                <tr key={r.id}>
                  <td>{r.seq}</td>
                  <td>{r.title}</td>
                  <td>
                    <select
                      value={levels[r.id]}
                      onChange={(e) => setLevels({ ...levels, [r.id]: e.target.value as Level })}
                    >
                      {LEVELS.map((l) => (
                        <option key={l} value={l}>
                          {levelLabel(l)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="small">{p ? p.visible.join(" · ") : "…"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {preview && (
          <div className="warnings" data-testid="export-warnings">
            {preview.warnings.map((w, i) => (
              <p key={i} className="warning small">
                {w}
              </p>
            ))}
            <p className="small muted">
              {t("The genesis record (author label and public key) is always included so signatures can be checked.")}
            </p>
          </div>
        )}
        <fieldset className="destinations" data-testid="export-destination">
          <legend>{t("Where should it go?")}</legend>
          <label className="check">
            <input type="radio" checked={dest === "zip"} onChange={() => setDest("zip")} data-testid="dest-zip" />
            {t("Download a zip file, to send yourself")}
          </label>
          <label className="check">
            <input type="radio" checked={dest === "repo"} onChange={() => setDest("repo")} data-testid="dest-repo" />
            {t("Into a git repository on this computer (and on to GitHub)")}
          </label>
          {dest === "repo" && (
            <div className="dest-detail">
              {repos.length > 0 && (
                <select value={repos.some((r) => r.path === repoPath) ? repoPath : ""} onChange={(e) => setRepoPath(e.target.value)}
                  aria-label={t("Repository")} data-testid="dest-repo-select">
                  {repos.map((r) => <option key={r.id} value={r.path}>{r.name} — {r.path}</option>)}
                  <option value="">{t("Another repository folder…")}</option>
                </select>
              )}
              {!repos.some((r) => r.path === repoPath) && (
                <input value={repoPath} onChange={(e) => setRepoPath(e.target.value)} data-testid="dest-repo-path"
                  placeholder={t("Folder of a git repository on this computer")} aria-label={t("Repository folder")} />
              )}
              <p className="note">
                {t("The bundle is unpacked into the folder provenance/{name}/ of the repository and committed there on its own; your other changes are left as they are. On GitHub, VERIFY.md then reads as a page.", { name: title.trim() || "evidence" })}
              </p>
              <label className="check">
                <input type="checkbox" checked={push} onChange={(e) => setPush(e.target.checked)} data-testid="dest-push" />
                {t("Also push it to GitHub (or wherever the repository's origin is)")}
              </label>
              {push && (
                <p className="warning small">{t("In a public repository everyone can then see what you chose to disclose above.")}</p>
              )}
            </div>
          )}
          <label className="check">
            <input type="radio" checked={dest === "zenodo"} onChange={() => setDest("zenodo")} data-testid="dest-zenodo" />
            {t("Zenodo, as a draft — to publish there and get a DOI")}
          </label>
          {dest === "zenodo" && (
            <div className="dest-detail">
              {zenodo?.connected ? (
                <p className="note" data-testid="zenodo-ready">
                  {zenodo.sandbox ? t("A private draft is made on Zenodo's test site.") : t("A private draft is made on Zenodo.")}{" "}
                  {t("Look at it there and publish it yourself: then it gets its DOI — and it can no longer be deleted.")}{" "}
                  <button type="button" className="link small" onClick={forgetZenodo}>{t("Disconnect Zenodo")}</button>
                </p>
              ) : (
                <ZenodoConnect onConnected={setZenodo} />
              )}
            </div>
          )}
        </fieldset>
        {done?.kind === "repo" && (
          <div className="status-box" data-testid="export-done">
            <p>{t("Saved in {folder}.", { folder: done.out.folder })}</p>
            {done.out.commit && <p className="small">{t("Committed as {commit}.", { commit: done.out.commit.slice(0, 12) })}</p>}
            {done.out.pushed && <p className="small">{t("Pushed to {remote}.", { remote: done.out.remote_url ?? "origin" })}</p>}
            {done.out.error && <p className="error small">{done.out.error}</p>}
          </div>
        )}
        {done?.kind === "zenodo" && (
          <div className="status-box" data-testid="export-done">
            <p>
              {t("The draft is on Zenodo.")}{" "}
              {done.out.html && <a href={done.out.html} target="_blank" rel="noopener noreferrer">{t("Open it on Zenodo")}</a>}
            </p>
            {done.out.doi && <p className="small">{t("Its DOI will be {doi} once you publish it.", { doi: done.out.doi })}</p>}
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <div className="actions">
          {projectId && (
            <a className="small table-link" href={tableUrl(projectId)} download data-testid="export-table"
              title={t("Opens in Excel or Numbers. A table is for reading and counting; it cannot be checked like the bundle.")}>
              {t("Download the steps as a table (CSV)")}
            </a>
          )}
          <span className="spacer" />
          <button className="secondary" onClick={onClose}>
            {done ? t("Done") : t("Cancel")}
          </button>
          <button className="primary" onClick={doExport} data-testid="do-export"
            disabled={busy || !preview || (dest === "repo" && !repoPath.trim()) || (dest === "zenodo" && !zenodo?.connected)}>
            {busy ? t("Working…") : dest === "repo" ? t("Put it into the repository") : dest === "zenodo" ? t("Make the Zenodo draft") : t("Make the zip")}
          </button>
        </div>
      </div>
    </div>
  );
}
