import { useState } from "react";
import { api } from "../api";
import { t } from "../i18n";

// A name for a new research project, in a dialog of the app's own: the browser's prompt box is
// bare, and in the app's window (D-058) it looked out of place.
export function NewProject({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const name = title.trim();
    if (!name || busy) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject(name);
      onCreated(project.id);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("New research project")}>
      <form className="modal narrow" data-testid="new-project" onSubmit={create}>
        <div className="modal-head">
          <h2>{t("New research project")}</h2>
          <button type="button" className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <label>
          {t("Name of the new research project")}
          <input autoFocus value={title} maxLength={200} data-testid="new-project-title"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && onClose()} />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" className="secondary" onClick={onClose}>{t("Cancel")}</button>
          <button type="submit" className="primary" disabled={busy || !title.trim()} data-testid="new-project-create">
            {t("Create project")}
          </button>
        </div>
      </form>
    </div>
  );
}
