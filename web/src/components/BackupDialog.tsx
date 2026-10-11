import { useState } from "react";
import { api, download } from "../api";

interface Props {
  defaultLocation: string | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

// One-click full backup: database, files and the password-protected signing key (PRD S7).
export function BackupDialog({ defaultLocation, onClose, onDone }: Props) {
  const [password, setPassword] = useState("");
  const [location, setLocation] = useState(defaultLocation ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { blob, path, filename } = await api.backup(password, location.trim() || undefined);
      if (!path) download(blob, filename);
      onDone(path ? `Backup written to ${path}` : "Backup downloaded.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Backup">
      <form className="modal" onSubmit={submit} data-testid="backup-dialog">
        <h2>Full backup</h2>
        <p className="small">
          One zip with the database, every stored file and your signing key. The key inside is encrypted with this
          password; the database and files are not, so keep the backup somewhere private (an external disk, an
          encrypted folder).
        </p>
        <label>
          Password for the key (at least 8 characters)
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        </label>
        <label>
          Backup folder <span className="muted">(optional, absolute path; remembered for next time)</span>
          <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="/Volumes/Backup/rprov" />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy || password.length < 8}>
            Create backup
          </button>
        </div>
      </form>
    </div>
  );
}

export function RestoreForm({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.restore(file, password);
      if (!out.verification.ok) setError("Restored, but verification reported failures — check the records.");
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="restore" data-testid="restore-form">
      <label>
        Backup file
        <input type="file" accept=".zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label>
        Backup password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <button className="secondary" disabled={busy || !file || !password}>
        Restore
      </button>
    </form>
  );
}
