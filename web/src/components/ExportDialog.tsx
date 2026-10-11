import { useEffect, useState } from "react";
import { api, download } from "../api";
import type { ExportPreview, TimelineRow } from "../types";

type Level = "full" | "structure" | "existence";
const LEVEL_LABELS: Record<Level, string> = {
  full: "Everything",
  structure: "Structure only",
  existence: "Existence only",
};

interface Props {
  rows: TimelineRow[];
  defaultTitle: string;
  onClose: () => void;
}

export function ExportDialog({ rows, defaultTitle, onClose }: Props) {
  const entries = rows.filter((r) => r.kind === "entry");
  const [title, setTitle] = useState(defaultTitle);
  const [levels, setLevels] = useState<Record<string, Level>>(() =>
    Object.fromEntries(entries.map((r) => [r.id, "structure" as Level])),
  );
  const [includeAdditions, setIncludeAdditions] = useState(true);
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selection = () => {
    const records: Record<string, string> = { ...levels };
    if (includeAdditions) {
      // Later additions (links, milestones, statements, retractions) travel with structure.
      rows.filter((r) => r.kind !== "entry" && r.kind !== "genesis").forEach((r) => (records[r.id] = "structure"));
    }
    return { title, records, default: "existence" };
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
  }, [levels, includeAdditions, title]);

  async function doExport() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.exportBundle(selection());
      const day = new Date().toISOString().slice(0, 10);
      download(blob, `provenance-${title.replace(/[^A-Za-z0-9._-]+/g, "-") || "evidence"}-${day}.zip`);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const setAll = (lvl: Level) => setLevels(Object.fromEntries(entries.map((r) => [r.id, lvl])));

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Export evidence bundle">
      <div className="modal wide" data-testid="export-dialog">
        <h2>Export evidence bundle</h2>
        <p className="small">
          A zip with a web report, a checker (<code>verify.py</code>) and manual instructions. The reader needs neither
          this app nor trust in you.
        </p>
        <label>
          Bundle name
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <div className="row small">
          Set all to:
          {(Object.keys(LEVEL_LABELS) as Level[]).map((l) => (
            <button key={l} type="button" className="secondary small" onClick={() => setAll(l)}>
              {LEVEL_LABELS[l]}
            </button>
          ))}
          <label className="check">
            <input type="checkbox" checked={includeAdditions} onChange={(e) => setIncludeAdditions(e.target.checked)} />
            include later additions
          </label>
        </div>
        <table className="export-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Record</th>
              <th>Disclose</th>
              <th>Will be visible</th>
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
                      {(Object.keys(LEVEL_LABELS) as Level[]).map((l) => (
                        <option key={l} value={l}>
                          {LEVEL_LABELS[l]}
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
              The genesis record (author label and public key) is always included so signatures can be checked.
            </p>
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" onClick={doExport} disabled={busy || !preview} data-testid="do-export">
            Export
          </button>
        </div>
      </div>
    </div>
  );
}
