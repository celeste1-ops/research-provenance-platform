import { useEffect, useState } from "react";
import { api, download } from "../api";
import type { ExportPreview, TimelineRow } from "../types";
import { lang, t, tx, type Lang } from "../i18n";

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
}

export function ExportDialog({ rows, defaultTitle, onClose, practice = false }: Props) {
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
      const blob = await api.exportBundle(selection());
      const day = new Date().toISOString().slice(0, 10);
      download(blob, `provenance-${title.replace(/[^\p{L}\p{N}._-]+/gu, "-") || "evidence"}-${day}.zip`);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
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
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button className="secondary" onClick={onClose}>
            {t("Cancel")}
          </button>
          <button className="primary" onClick={doExport} disabled={busy || !preview} data-testid="do-export">
            {t("Make the zip")}
          </button>
        </div>
      </div>
    </div>
  );
}
