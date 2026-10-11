import { useEffect, useState } from "react";
import { api, download } from "../api";
import type { BackupStatus, BackupSuggestion, LocationCheck } from "../types";
import { timeAgo } from "../util";
import { dev, keychainName } from "../device";
import { gap, t, tx } from "../i18n";

const bold = { b: (s: string) => <b>{s}</b> };
const boldMono = { b: (s: string) => <b>{s}</b>, mono: (s: string) => <span className="mono">{s}</span> };

// Choose a folder + password once; from then on every change is backed up automatically,
// fully encrypted. Used in first-run onboarding and in the Backup dialog. The first time,
// a printable recovery code is shown (D-039).
// How long the backup form waits for the list of suggested folders before showing without it.
const SUGGESTIONS_WAIT_MS = 5000;

export function BackupSetup({
  current,
  onDone,
  onSkip,
  submitLabel,
}: {
  current?: BackupStatus | null;
  onDone: (status: BackupStatus) => void;
  onSkip?: () => void;
  submitLabel?: string;
}) {
  // null while still looking: the form is shown once the list is known, so nothing moves under
  // the pointer (on Windows the list can take a few seconds and used to push the button down).
  const [suggestions, setSuggestions] = useState<BackupSuggestion[] | null>(null);
  const [location, setLocation] = useState(current?.location ?? "");
  const [check, setCheck] = useState<LocationCheck | null>(null);
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<BackupStatus | null>(null);

  useEffect(() => {
    let settled = false;
    const settle = (s: BackupSuggestion[]) => {
      if (settled) return; // a list that arrives after giving up is ignored
      settled = true;
      setSuggestions(s);
      if (s.length > 0) setLocation((typed) => typed || s[0].path);
    };
    const giveUp = window.setTimeout(() => settle([]), SUGGESTIONS_WAIT_MS);
    api.backupSuggestions().then(settle).catch(() => settle([]));
    return () => {
      settled = true;
      window.clearTimeout(giveUp);
    };
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
      setError(t("The two passwords are not the same."));
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

  if (suggestions === null) {
    return (
      <p className="muted" data-testid="backup-looking">
        {t("Looking for good places for backups on this {device}…", { device: dev() })}
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="backup-setup" data-testid="backup-setup">
      <div className="field">
        <span className="field-label">{t("Where should backups go?")}</span>
        {suggestions.length > 0 && (
          <div className="choice-list">
            {suggestions.map((s) => (
              <label key={s.path} className={`choice ${location === s.path ? "selected" : ""}`}>
                <input type="radio" name="loc" checked={location === s.path} onChange={() => setLocation(s.path)} />
                <b>{s.label}</b>
                <span className="muted small">{s.kind === "synced" ? t("kept in sync off this {device}", { device: dev() }) : t("external drive")}</span>
              </label>
            ))}
          </div>
        )}
        <input
          aria-label={t("Backup folder")}
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="/Volumes/MyDrive/Research Provenance Backups"
        />
        {/* Space is kept for this line, so the button below does not move when it appears. */}
        <div className="location-check-slot">
          {check && (
            <p className={`small location-check ${check.safe ? "ok" : "warn"}`} data-testid="location-check">
              {check.safe ? "✓ " : "⚠ "}
              <b>{check.label}</b>
              {check.creates && ` — ${t("the folder will be created")}`}
              {check.warning && <span className="block">{check.warning}</span>}
            </p>
          )}
        </div>
        <p className="note">
          {tx("Pick a place that is <b>not only on this {device}</b>: an external drive, or a folder kept in sync by a service you already use (iCloud Drive, OneDrive, Dropbox…). Only the encrypted backup files go there — the app's working data stays in its own folder on this {device}.", bold, { device: dev() })}
        </p>
      </div>
      <label>
        {t("Backup password (at least 8 characters)")}
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
      </label>
      <label>
        {t("Repeat the password")}
        <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} minLength={8} required />
      </label>
      <p className="warning small" data-testid="password-warning">
        {tx("<b>If you forget this password, your backups can't be opened</b> — nobody can open them, including us. Write it down somewhere safe.", bold)}
        {gap()}
        {current?.recovery?.configured
          ? t("Your printed recovery code also opens them.")
          : t("Next you get a recovery code to print: it opens your backups if the password is lost.")}
        {gap()}
        {t("This {device} remembers the password (in the {keychain}) so backups run by themselves.", { device: dev(), keychain: keychainName() })}
      </p>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !location.trim() || password.length < 8 || check?.ok === false}>
        {busy ? t("Backing up…") : (submitLabel ?? t("Turn on automatic backup"))}
      </button>
      {onSkip && (
        <p className="small center">
          <button type="button" className="link muted" onClick={onSkip}>
            {t("Skip for now")}
          </button>{" "}
          <span className="muted">{t("(you can turn it on later from the backup button at the top)")}</span>
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
        <h2>{t("Your backup recovery code")}</h2>
        <p className="recovery-code mono" data-testid="recovery-code-value">
          {code}
        </p>
        <p className="small">
          {tx("Research history · made {date}. If the backup password is ever lost, this code opens your backups instead: install the app on a {device}, choose <b>Restore from a backup</b>, pick the newest <mono>.rprovbackup</mono> file and click <b>Use the recovery code instead</b>.", boldMono, { date: made, device: dev() })}
        </p>
        {fingerprint && (
          <p className="small" data-testid="recovery-fingerprint">
            {t("Signing key:")} <b className="mono">{fingerprint}</b> — {t("after a restore with this code the app shows the signing key it brought back; it must be this one. If it is not, the backup is not yours: don't use it.")}
          </p>
        )}
      </div>
      <p className="warning small">
        {t("This is the only time the code is shown — the app does not keep it. Print it or write it down, and keep it somewhere safe away from this {device} (not in the same folder as the backups).", { device: dev() })}
      </p>
      <div className="row">
        <button type="button" className="secondary" onClick={() => window.print()}>
          {t("Print")}
        </button>
        <label className="check">
          <input type="checkbox" checked={kept} onChange={(e) => setKept(e.target.checked)} />{" "}
          {t("I have printed it or written it down")}
        </label>
      </div>
      <div className="actions">
        <button type="button" className="primary" disabled={!kept} onClick={onDone}>
          {t("Continue")}
        </button>
      </div>
    </div>
  );
}

export function BackupPill({ status, onClick }: { status: BackupStatus | null; onClick: () => void }) {
  const st = status?.state ?? "off";
  const text =
    st === "ok"
      ? t("Last backup: {when} ✓", { when: timeAgo(status?.last_backup) })
      : st === "paused"
        ? t("Backup paused — confirm to resume")
        : st === "other-copy"
        ? t("Another {device} is backing up here too", { device: dev() })
        : st === "same-disk"
        ? t("Backup is on this {device} only", { device: dev() })
        : st === "keychain-denied"
        ? t("Backup waits for the {keychain}", { keychain: keychainName() })
        : st === "error"
          ? t("Backup failed")
          : status?.needs_password
            ? t("Backup needs your password")
            : t("Backup not set up");
  return (
    <button className={`pill pill-${st}`} onClick={onClick} data-testid="backup-pill" title={t("Backup status")}>
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
  const [editing, setEditing] = useState(!status?.configured && status?.state !== "paused" && !status?.keychain_denied);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [oneOff, setOneOff] = useState("");
  const [newCode, setNewCode] = useState<{ code: string; fingerprint?: string | null } | null>(null);

  async function runNow() {
    setBusy(true);
    setError(null);
    try {
      const out = await api.backupRun();
      onChanged(t("Backup written to {path}", { path: out.path }));
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
      onChanged(t("Automatic backup resumed. A new backup was written."));
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
      onChanged(t("OK — no more warnings unless that other copy writes a backup again."));
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
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Backup")}>
      <div className="modal" data-testid="backup-dialog">
        <div className="modal-head">
          <h2>{t("Backup")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>
            ✕
          </button>
        </div>
        {newCode ? (
          <RecoveryCodeSheet code={newCode.code} fingerprint={newCode.fingerprint}
            onDone={() => onChanged(t("New recovery code made. Keep the printed copy safe."))} />
        ) : (
          <>
            <p className="small">
              {tx("A backup holds everything — your steps, files, stamps and signing key — fully encrypted. If this {device} is lost or breaks, install the app on a new {device} and choose <b>Restore from a backup</b>.", bold, { device: dev() })}
            </p>
            {status?.data_dir_warning && <p className="error small">{status.data_dir_warning}</p>}
            {status?.keychain_denied && !editing && (
              <div className="status-box state-error" data-testid="backup-keychain-denied">
                {t("The {keychain} refused access to the backup password, so automatic backups wait. Close this window and click Try again at the top of the page; when the system asks, choose “Always Allow”.", { keychain: keychainName() })}
              </div>
            )}
            {status?.state === "paused" && !editing && (
              <div className="status-box state-paused" data-testid="backup-paused">
                <div>
                  {status.paused_reason === "restored"
                    ? tx("<b>Automatic backup is paused</b> because this copy was restored from a backup.", bold)
                    : status.paused_reason === "copied"
                      ? dev() === "Mac"
                        ? tx("<b>Automatic backup is paused</b> because this data folder was copied from somewhere else (for example by Migration Assistant or Time Machine).", bold)
                        : tx("<b>Automatic backup is paused</b> because this data folder was copied from somewhere else (for example from another computer or by a backup tool).", bold)
                      : tx("<b>Automatic backup is paused</b>.", bold)}
                </div>
                <div className="small">
                  {t("Folder:")} <span className="mono">{status.location}</span> ({status.where?.label})
                </div>
                {status.other_copy && (
                  <p className="error small">
                    {t("Another copy of this research wrote a backup into this folder at {time}, after the backup you restored from. Is the old {device} still running? Quit the app there first, or choose a different folder.", { time: status.other_copy.last_backup, device: dev() })}
                  </p>
                )}
                <p className="warning small">
                  {t("Resume only on the {device} you will keep using. If another {device} — or the copy you restored from — still backs up into this folder, choose a different folder instead. If this was only a test of your backup, don't resume: close this copy and delete its folder.", { device: dev() })}
                </p>
                {status.needs_password ? (
                  <>
                    <p className="small">
                      {t("To resume, set a backup password for this {device} (it can be the same as before). Your printed recovery code stays valid.", { device: dev() })}
                    </p>
                    <BackupSetup
                      current={status}
                      submitLabel={t("Set password and resume")}
                      onDone={() => onChanged(t("Automatic backup resumed. A new backup was written."))}
                    />
                  </>
                ) : (
                  <div className="row">
                    <button className="primary small" onClick={resume} disabled={busy}>
                      {t("Resume automatic backup to this folder")}
                    </button>
                    <button className="secondary small" onClick={() => setEditing(true)}>
                      {t("Choose a different folder")}
                    </button>
                  </div>
                )}
              </div>
            )}
            {status?.other_copy && status.state !== "paused" && !editing && (
              <div className="status-box state-other-copy" data-testid="other-copy">
                <div>
                  {tx("<b>Another copy of this research is also backing up into this folder</b> — last at {time}.", bold, { time: status.other_copy.last_backup })}
                </div>
                <p className="small">
                  {tx("That usually means a second {device} (for example the old one, after you restored onto a new one) still runs the app. Use <b>only one {device}</b> to add steps: if both keep adding steps, the two histories split, and a restore can bring back only one of them. Quit the app on the {device} you no longer use. Your own backups are not affected — each copy keeps its own files.", bold, { device: dev() })}
                </p>
                <div className="row">
                  <button className="secondary small" onClick={acknowledge} disabled={busy}>
                    {t("The other copy is gone — stop warning")}
                  </button>
                  <button className="secondary small" onClick={() => setEditing(true)}>
                    {t("Choose a different folder")}
                  </button>
                </div>
              </div>
            )}
            {status?.configured && status.state !== "paused" && !editing && (
              <div className={`status-box state-${status.state}`}>
                <div>
                  {tx("<b>Automatic backup is on</b> — after every change, keeping the last {n}.", bold, { n: status.keep })}
                </div>
                <div className="small">
                  {t("Folder:")} <span className="mono">{status.location}</span> ({status.where?.label})
                </div>
                <div className="small">{t("Last backup:")} {timeAgo(status.last_backup)}</div>
                {status.where?.warning && <p className="warning small">{status.where.warning}</p>}
                {status.last_error && <p className="error small">{t("Last attempt failed:")} {status.last_error}</p>}
                <div className="row">
                  <button className="secondary small" onClick={runNow} disabled={busy}>
                    {t("Back up now")}
                  </button>
                  <button className="secondary small" onClick={() => setEditing(true)}>
                    {t("Change folder or password")}
                  </button>
                </div>
              </div>
            )}
            {status?.configured && status.state !== "paused" && !editing && (
              <div className="status-box" data-testid="recovery-status">
                {status.recovery?.configured ? (
                  <>
                    <div className="small">
                      {tx("<b>Recovery code:</b> made {date}. It opens your backups if the password is lost.", bold, { date: status.recovery.created_local?.slice(0, 10) ?? "" })}
                    </div>
                    <button className="link small" onClick={makeCode} disabled={busy}>
                      {t("Lost it? Make a new recovery code")}
                    </button>
                  </>
                ) : (
                  <>
                    <p className="warning small">
                      {tx("<b>No recovery code yet.</b> Without one, a forgotten password means the backups can't be opened.", bold)}
                    </p>
                    <button className="secondary small" onClick={makeCode} disabled={busy}>
                      {t("Make a recovery code")}
                    </button>
                  </>
                )}
              </div>
            )}
            {editing && (
              <BackupSetup
                current={status}
                submitLabel={status?.configured ? t("Save and back up") : t("Turn on automatic backup")}
                onDone={(st) => {
                  setEditing(false);
                  onChanged(
                    st.last_file
                      ? t("Automatic backup is on. First backup written to {path}.", { path: st.last_file })
                      : t("Automatic backup is on. First backup written."),
                  );
                }}
              />
            )}
            <details className="small more">
              <summary>{t("Download a single backup file instead")}</summary>
              <div className="row">
                <input type="password" placeholder={t("Password for this file")} value={oneOff}
                  onChange={(e) => setOneOff(e.target.value)} />
                <button className="secondary small" disabled={busy || oneOff.length < 8} onClick={downloadOnce}>
                  {t("Download")}
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
            {t("Restored with the recovery code. Signing key:")} <b className="mono">{restoredFingerprint}</b>.{" "}
            {t("Check that this is the signing key printed on your recovery sheet. If it is different, this backup is not yours — don't use it.")}
          </p>
        )}
        {restoredWithProblems && (
          <p className="error">
            {t("The check found problems with some records. Open the app and look at the records marked as failed before relying on them; keep the backup file.")}
          </p>
        )}
        <button className="primary" onClick={onDone}>
          {t("Open the app")}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="restore" data-testid="restore-form">
      <label>
        {t("Backup file")}
        <input type="file" accept=".rprovbackup,.zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      {useCode ? (
        <label>
          {t("Recovery code")}
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="XXXXXX-XXXXXX-XXXXXX-XXXXXX"
            autoComplete="off" spellCheck={false} />
        </label>
      ) : (
        <label>
          {t("Backup password")}
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
      )}
      <p className="small">
        <button type="button" className="link" onClick={() => setUseCode(!useCode)}>
          {useCode ? t("Use the backup password instead") : t("Forgot the password? Use the recovery code instead")}
        </button>
      </p>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy || !file || (useCode ? !code.trim() : !password)}>
        {busy ? t("Restoring…") : t("Restore my research")}
      </button>
    </form>
  );
}
