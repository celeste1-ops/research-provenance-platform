import { useEffect, useState } from "react";
import { api, download } from "../api";
import type { BackupStatus, BackupSuggestion } from "../types";
import { timeAgo } from "../util";

// Choose a folder + password once; from then on every change is backed up automatically,
// fully encrypted. Used in first-run onboarding and in the Backup dialog.
export function BackupSetup({
  current,
  onDone,
  submitLabel = "Turn on automatic backup",
}: {
  current?: BackupStatus | null;
  onDone: (status: BackupStatus) => void;
  submitLabel?: string;
}) {
  const [suggestions, setSuggestions] = useState<BackupSuggestion[]>([]);
  const [location, setLocation] = useState(current?.location ?? "");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .backupSuggestions()
      .then((s) => {
        setSuggestions(s);
        if (!location && s.length > 0) setLocation(s[0].path);
      })
      .catch(() => setSuggestions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== again) {
      setError("The two passwords are not the same.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onDone(await api.backupSettings(location.trim(), password, true));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="backup-setup" data-testid="backup-setup">
      <div className="field">
        <span className="field-label">Where should backups go?</span>
        {suggestions.length > 0 && (
          <div className="choice-list">
            {suggestions.map((s) => (
              <label key={s.path} className={`choice ${location === s.path ? "selected" : ""}`}>
                <input type="radio" name="loc" checked={location === s.path} onChange={() => setLocation(s.path)} />
                <b>{s.label}</b>
                <span className="muted small">{s.kind === "synced" ? "kept in sync off this Mac" : "external drive"}</span>
              </label>
            ))}
          </div>
        )}
        <input
          aria-label="Backup folder"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="/Volumes/MyDrive/Research Provenance Backups"
        />
        <p className="note">
          Pick a place that is <b>not only on this Mac</b>: an external drive, or a folder kept in sync by a service
          you already use (iCloud Drive, Dropbox…). The folder is created if needed.
        </p>
      </div>
      <label>
        Backup password (at least 8 characters)
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
      </label>
      <label>
        Repeat the password
        <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} minLength={8} required />
      </label>
      <p className="warning small">
        Write this password down somewhere safe. Backups are fully encrypted with it — without it nobody, including
        us, can open them. This Mac remembers it (in the Keychain) so backups run by themselves.
      </p>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !location.trim() || password.length < 8}>
        {busy ? "Backing up…" : submitLabel}
      </button>
    </form>
  );
}

export function BackupPill({ status, onClick }: { status: BackupStatus | null; onClick: () => void }) {
  const st = status?.state ?? "off";
  const text =
    st === "ok"
      ? `Backed up · ${timeAgo(status?.last_backup)}`
      : st === "same-disk"
        ? "Backup is on this Mac only"
        : st === "error"
          ? "Backup failed"
          : status?.needs_password
            ? "Backup needs your password"
            : "Backup not set up";
  return (
    <button className={`pill pill-${st}`} onClick={onClick} data-testid="backup-pill" title="Backup status">
      <span className="dot" /> {text}
    </button>
  );
}

export function BackupDialog({
  status,
  onClose,
  onChanged,
}: {
  status: BackupStatus | null;
  onClose: () => void;
  onChanged: (message: string) => void;
}) {
  const [editing, setEditing] = useState(!status?.configured);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oneOff, setOneOff] = useState("");

  async function runNow() {
    setBusy(true);
    setError(null);
    try {
      const out = await api.backupRun();
      onChanged(`Backup written to ${out.path}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function downloadOnce() {
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await api.backupDownload(oneOff);
      download(blob, filename);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Backup">
      <div className="modal" data-testid="backup-dialog">
        <div className="modal-head">
          <h2>Backup</h2>
          <button className="link" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="small">
          A backup holds everything — your steps, files, time proofs and signing key — fully encrypted. If this Mac is
          lost or breaks, install the app on a new Mac and choose <b>Restore from a backup</b>.
        </p>
        {status?.configured && !editing && (
          <div className={`status-box state-${status.state}`}>
            <div>
              <b>Automatic backup is on</b> — after every change, keeping the last {status.keep}.
            </div>
            <div className="small">
              Folder: <span className="mono">{status.location}</span> ({status.where?.label})
            </div>
            <div className="small">Last backup: {timeAgo(status.last_backup)}</div>
            {status.where?.warning && <p className="warning small">{status.where.warning}</p>}
            {status.last_error && <p className="error small">Last attempt failed: {status.last_error}</p>}
            <div className="row">
              <button className="secondary small" onClick={runNow} disabled={busy}>
                Back up now
              </button>
              <button className="secondary small" onClick={() => setEditing(true)}>
                Change folder or password
              </button>
            </div>
          </div>
        )}
        {editing && (
          <BackupSetup
            current={status}
            submitLabel={status?.configured ? "Save and back up" : "Turn on automatic backup"}
            onDone={(st) => {
              setEditing(false);
              onChanged(`Automatic backup is on. First backup written${st.last_file ? ` to ${st.last_file}` : ""}.`);
            }}
          />
        )}
        <details className="small more">
          <summary>Download a single backup file instead</summary>
          <div className="row">
            <input type="password" placeholder="Password for this file" value={oneOff}
              onChange={(e) => setOneOff(e.target.value)} />
            <button className="secondary small" disabled={busy || oneOff.length < 8} onClick={downloadOnce}>
              Download
            </button>
          </div>
        </details>
        {error && <p className="error">{error}</p>}
      </div>
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
        <input type="file" accept=".rprovbackup,.zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label>
        Backup password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !file || !password}>
        {busy ? "Restoring…" : "Restore my research"}
      </button>
    </form>
  );
}
