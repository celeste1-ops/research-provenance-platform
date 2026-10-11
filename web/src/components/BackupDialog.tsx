import { useEffect, useState } from "react";
import { api, download } from "../api";
import type { BackupStatus, BackupSuggestion, LocationCheck } from "../types";
import { timeAgo } from "../util";
import { dev, keychainName } from "../device";

// Choose a folder + password once; from then on every change is backed up automatically,
// fully encrypted. Used in first-run onboarding and in the Backup dialog. The first time,
// a printable recovery code is shown (D-039).
export function BackupSetup({
  current,
  onDone,
  onSkip,
  submitLabel = "Turn on automatic backup",
}: {
  current?: BackupStatus | null;
  onDone: (status: BackupStatus) => void;
  onSkip?: () => void;
  submitLabel?: string;
}) {
  const [suggestions, setSuggestions] = useState<BackupSuggestion[]>([]);
  const [location, setLocation] = useState(current?.location ?? "");
  const [check, setCheck] = useState<LocationCheck | null>(null);
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<BackupStatus | null>(null);

  useEffect(() => {
    api
      .backupSuggestions()
      .then((s) => {
        setSuggestions(s);
        // Only fill in an empty field: the list can arrive after the author typed a folder.
        if (s.length > 0) setLocation((typed) => typed || s[0].path);
      })
      .catch(() => setSuggestions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Say where the chosen folder really is while the author types or picks one.
  useEffect(() => {
    if (!location.trim()) {
      setCheck(null);
      return;
    }
    let live = true;
    const t = window.setTimeout(() => {
      api
        .backupCheck(location.trim())
        .then((c) => live && setCheck(c))
        .catch(() => live && setCheck(null));
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
  }, [location]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== again) {
      setError("The two passwords are not the same.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const st = await api.backupSettings(location.trim(), password, true);
      if (st.recovery_code) setCreated(st);
      else onDone(st);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (created?.recovery_code) {
    return (
      <RecoveryCodeSheet code={created.recovery_code} fingerprint={created.key_fingerprint}
        onDone={() => onDone(created)} />
    );
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
                <span className="muted small">{s.kind === "synced" ? `kept in sync off this ${dev()}` : "external drive"}</span>
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
        {check && (
          <p className={`small location-check ${check.safe ? "ok" : "warn"}`} data-testid="location-check">
            {check.safe ? "✓ " : "⚠ "}
            <b>{check.label}</b>
            {check.creates && " — the folder will be created"}
            {check.warning && <span className="block">{check.warning}</span>}
          </p>
        )}
        <p className="note">
          Pick a place that is <b>not only on this {dev()}</b>: an external drive, or a folder kept in sync by a service
          you already use (iCloud Drive, Dropbox…). Only the encrypted backup files go there — the app's working data
          stays in its own folder on this {dev()}.
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
      <p className="warning small" data-testid="password-warning">
        <b>If you forget this password, your backups can't be opened</b> — nobody can open them, including us. Write it
        down somewhere safe. {current?.recovery?.configured ? "Your printed recovery code also opens them." : "Next you get a recovery code to print: it opens your backups if the password is lost."}{" "}
        This {dev()} remembers the password (in the {keychainName()}) so backups run by themselves.
      </p>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !location.trim() || password.length < 8 || check?.ok === false}>
        {busy ? "Backing up…" : submitLabel}
      </button>
      {onSkip && (
        <p className="small center">
          <button type="button" className="link muted" onClick={onSkip}>
            Skip for now
          </button>{" "}
          <span className="muted">(you can turn it on later from the backup button at the top)</span>
        </p>
      )}
    </form>
  );
}

// Shown once: the code is never stored by the app, only the public half of a key made from it.
export function RecoveryCodeSheet({ code, fingerprint, onDone }: {
  code: string;
  fingerprint?: string | null;
  onDone: () => void;
}) {
  const [kept, setKept] = useState(false);
  const made = new Date().toISOString().slice(0, 10);
  return (
    <div className="recovery" data-testid="recovery-code">
      <div className="print-sheet">
        <h2>Your backup recovery code</h2>
        <p className="recovery-code mono" data-testid="recovery-code-value">
          {code}
        </p>
        <p className="small">
          Research history · made {made}. If the backup password is ever lost, this code opens your backups instead:
          install the app on a {dev()}, choose <b>Restore from a backup</b>, pick the newest <span className="mono">.rprovbackup</span>{" "}
          file and click <b>Use the recovery code instead</b>.
        </p>
        {fingerprint && (
          <p className="small" data-testid="recovery-fingerprint">
            Signing key: <b className="mono">{fingerprint}</b> — after a restore with this code the app shows the
            signing key it brought back; it must be this one. If it is not, the backup is not yours: don't use it.
          </p>
        )}
      </div>
      <p className="warning small">
        This is the only time the code is shown — the app does not keep it. Print it or write it down, and keep it
        somewhere safe away from this {dev()} (not in the same folder as the backups).
      </p>
      <div className="row">
        <button type="button" className="secondary" onClick={() => window.print()}>
          Print
        </button>
        <label className="check">
          <input type="checkbox" checked={kept} onChange={(e) => setKept(e.target.checked)} /> I have printed it or
          written it down
        </label>
      </div>
      <div className="actions">
        <button type="button" className="primary" disabled={!kept} onClick={onDone}>
          Continue
        </button>
      </div>
    </div>
  );
}

export function BackupPill({ status, onClick }: { status: BackupStatus | null; onClick: () => void }) {
  const st = status?.state ?? "off";
  const text =
    st === "ok"
      ? `Last backup: ${timeAgo(status?.last_backup)} ✓`
      : st === "paused"
        ? "Backup paused — confirm to resume"
        : st === "other-copy"
        ? `Another ${dev()} is backing up here too`
        : st === "same-disk"
        ? `Backup is on this ${dev()} only`
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
  // A paused copy first sees why it is paused (D-040), even when it has no password yet.
  const [editing, setEditing] = useState(!status?.configured && status?.state !== "paused");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oneOff, setOneOff] = useState("");
  const [newCode, setNewCode] = useState<{ code: string; fingerprint?: string | null } | null>(null);

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

  async function resume() {
    setBusy(true);
    setError(null);
    try {
      await api.backupResume();
      onChanged("Automatic backup resumed. A new backup was written.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge() {
    setBusy(true);
    setError(null);
    try {
      await api.backupAcknowledgeOtherCopy();
      onChanged("OK — no more warnings unless that other copy writes a backup again.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function makeCode() {
    setBusy(true);
    setError(null);
    try {
      const out = await api.backupNewRecoveryCode();
      setNewCode({ code: out.recovery_code, fingerprint: out.status.key_fingerprint });
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
        {newCode ? (
          <RecoveryCodeSheet code={newCode.code} fingerprint={newCode.fingerprint}
            onDone={() => onChanged("New recovery code made. Keep the printed copy safe.")} />
        ) : (
          <>
            <p className="small">
              A backup holds everything — your steps, files, stamps and signing key — fully encrypted. If this {dev()} is
              lost or breaks, install the app on a new {dev()} and choose <b>Restore from a backup</b>.
            </p>
            {status?.data_dir_warning && <p className="error small">{status.data_dir_warning}</p>}
            {status?.state === "paused" && !editing && (
              <div className="status-box state-paused" data-testid="backup-paused">
                <div>
                  <b>Automatic backup is paused</b>
                  {status.paused_reason === "restored"
                    ? " because this copy was restored from a backup."
                    : status.paused_reason === "copied"
                      ? ` because this data folder was copied from somewhere else (for example ${
                          dev() === "Mac" ? "by Migration Assistant or Time Machine" : "from another computer or by a backup tool"
                        }).`
                      : "."}
                </div>
                <div className="small">
                  Folder: <span className="mono">{status.location}</span> ({status.where?.label})
                </div>
                {status.other_copy && (
                  <p className="error small">
                    Another copy of this research wrote a backup into this folder at {status.other_copy.last_backup},
                    after the backup you restored from. Is the old {dev()} still running? Quit the app there first, or
                    choose a different folder.
                  </p>
                )}
                <p className="warning small">
                  Resume only on the {dev()} you will keep using. If another {dev()} — or the copy you restored from — still
                  backs up into this folder, choose a different folder instead. If this was only a test of your backup,
                  don't resume: close this copy and delete its folder.
                </p>
                {status.needs_password ? (
                  <>
                    <p className="small">
                      To resume, set a backup password for this {dev()} (it can be the same as before). Your printed
                      recovery code stays valid.
                    </p>
                    <BackupSetup
                      current={status}
                      submitLabel="Set password and resume"
                      onDone={() => onChanged("Automatic backup resumed. A new backup was written.")}
                    />
                  </>
                ) : (
                  <div className="row">
                    <button className="primary small" onClick={resume} disabled={busy}>
                      Resume automatic backup to this folder
                    </button>
                    <button className="secondary small" onClick={() => setEditing(true)}>
                      Choose a different folder
                    </button>
                  </div>
                )}
              </div>
            )}
            {status?.other_copy && status.state !== "paused" && !editing && (
              <div className="status-box state-other-copy" data-testid="other-copy">
                <div>
                  <b>Another copy of this research is also backing up into this folder</b> — last at{" "}
                  {status.other_copy.last_backup}.
                </div>
                <p className="small">
                  That usually means a second {dev()} (for example the old one, after you restored onto a new one) still
                  runs the app. Use <b>only one {dev()}</b> to add steps: if both keep adding steps, the two histories split,
                  and a restore can bring back only one of them. Quit the app on the {dev()} you no longer use. Your own
                  backups are not affected — each copy keeps its own files.
                </p>
                <div className="row">
                  <button className="secondary small" onClick={acknowledge} disabled={busy}>
                    The other copy is gone — stop warning
                  </button>
                  <button className="secondary small" onClick={() => setEditing(true)}>
                    Choose a different folder
                  </button>
                </div>
              </div>
            )}
            {status?.configured && status.state !== "paused" && !editing && (
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
            {status?.configured && status.state !== "paused" && !editing && (
              <div className="status-box" data-testid="recovery-status">
                {status.recovery?.configured ? (
                  <>
                    <div className="small">
                      <b>Recovery code:</b> made {status.recovery.created_local?.slice(0, 10)}. It opens your backups if
                      the password is lost.
                    </div>
                    <button className="link small" onClick={makeCode} disabled={busy}>
                      Lost it? Make a new recovery code
                    </button>
                  </>
                ) : (
                  <>
                    <p className="warning small">
                      <b>No recovery code yet.</b> Without one, a forgotten password means the backups can't be opened.
                    </p>
                    <button className="secondary small" onClick={makeCode} disabled={busy}>
                      Make a recovery code
                    </button>
                  </>
                )}
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
          </>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}

export function RestoreForm({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [useCode, setUseCode] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoredWithProblems, setRestoredWithProblems] = useState(false);
  const [restoredFingerprint, setRestoredFingerprint] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.restore(file, useCode ? { recoveryCode: code } : { password });
      if (!out.verification.ok) setRestoredWithProblems(true);
      // Anyone who can write to the backup folder could leave a file that opens with the recovery
      // code (its key is public); the signing key printed on the recovery sheet tells them apart.
      if (out.opened_with === "recovery code") setRestoredFingerprint(out.key_fingerprint);
      else if (out.verification.ok) onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (restoredWithProblems || restoredFingerprint) {
    return (
      <div className="restore" data-testid="restore-result">
        {restoredFingerprint && (
          <p data-testid="restored-fingerprint">
            Restored with the recovery code. Signing key: <b className="mono">{restoredFingerprint}</b>. Check that this
            is the signing key printed on your recovery sheet. If it is different, this backup is not yours — don't
            use it.
          </p>
        )}
        {restoredWithProblems && (
          <p className="error">
            The check found problems with some records. Open the app and look at the records marked as failed before
            relying on them; keep the backup file.
          </p>
        )}
        <button className="primary" onClick={onDone}>
          Open the app
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="restore" data-testid="restore-form">
      <label>
        Backup file
        <input type="file" accept=".rprovbackup,.zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      {useCode ? (
        <label>
          Recovery code
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="XXXXXX-XXXXXX-XXXXXX-XXXXXX"
            autoComplete="off" spellCheck={false} />
        </label>
      ) : (
        <label>
          Backup password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
      )}
      <p className="small">
        <button type="button" className="link" onClick={() => setUseCode(!useCode)}>
          {useCode ? "Use the backup password instead" : "Forgot the password? Use the recovery code instead"}
        </button>
      </p>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !file || (useCode ? !code.trim() : !password)}>
        {busy ? "Restoring…" : "Restore my research"}
      </button>
    </form>
  );
}
