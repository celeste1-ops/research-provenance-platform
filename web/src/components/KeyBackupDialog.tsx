import { useState } from "react";
import { api, download } from "../api";

export function KeyBackupDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== again) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const blob = await api.exportKey(password);
      download(blob, "rprov-signing-key-backup.pem");
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Back up signing key">
      <form className="modal" onSubmit={submit} data-testid="key-backup-dialog">
        <h2>Back up your signing key</h2>
        <p className="small">
          The backup is encrypted with this password. Keep the file and the password somewhere safe and separate. If
          the key is lost, new records start a new identity; old records stay verifiable.
        </p>
        <label>
          Password (at least 8 characters)
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        </label>
        <label>
          Repeat password
          <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} minLength={8} required />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy || password.length < 8}>
            Download backup
          </button>
        </div>
      </form>
    </div>
  );
}
