import { useState } from "react";
import { api, getSpace } from "../api";
import { t } from "../i18n";
import type { Project } from "../types";

// "Quick note" (DECISIONS D-047): one box, one button. The first line becomes the title, the
// rest the text; it is saved as a note and stamped like any step. Also opened from the menu
// bar / tray icon.
export function QuickNote({ projects, projectId, onClose, onSaved }: {
  projects: Project[];
  projectId: string;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const [text, setText] = useState("");
  const [project, setProject] = useState(projectId || projects[0]?.id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [first, ...rest] = text.trim().split("\n");
  const title = (first ?? "").trim().slice(0, 200);

  async function save() {
    if (!title || !project) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("project_id", project);
    form.append("node_type", "note");
    form.append("title", title);
    const body = rest.join("\n").trim();
    if (body) form.append("body", body);
    try {
      const out = await api.createEntry(form);
      onSaved(out.id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Quick note")}>
      <div className="modal" data-testid="quick-note">
        <div className="modal-head">
          <h2>{t("Quick note")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <textarea
          autoFocus
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void save();
            if (e.key === "Escape") onClose();
          }}
          placeholder={t("What happened? The first line becomes the title.")}
          data-testid="quick-note-text"
        />
        {projects.length > 1 && (
          <label>
            {t("Project")}
            <select value={project} onChange={(e) => setProject(e.target.value)} data-testid="quick-note-project">
              {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
            </select>
          </label>
        )}
        {error && <p className="error">{error}</p>}
        <p className="note">
          {getSpace() === "real"
            ? t("Saved as a note in My research, with its date stamps. It can't be changed or deleted afterwards — later you can add to it.")
            : getSpace() === "example" ? t("Saved as a note in the example.") : t("Saved as a note in the practice space.")}
        </p>
        <div className="actions">
          <button className="secondary" onClick={onClose}>{t("Cancel")}</button>
          <button className="primary" onClick={save} disabled={busy || !title || !project} data-testid="quick-note-save">
            {busy ? t("Saving…") : t("Save note")}
          </button>
        </div>
      </div>
    </div>
  );
}
