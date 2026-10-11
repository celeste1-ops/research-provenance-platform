import { useState } from "react";
import { api } from "../api";
import { HOME_NOTE } from "../labels";
import { BackupSetup, RestoreForm } from "./BackupDialog";

// First run: (1) your name + first project, (2) automatic backup. Or restore instead.
export function Setup({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<"welcome" | "backup" | "restore">("welcome");
  const [label, setLabel] = useState("");
  const [project, setProject] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createIdentity(label);
      await api.createProject(project.trim() || "My research");
      setStep("backup");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="setup">
      <div className="card wide">
        <div className="steps-indicator small muted">
          {step === "restore" ? "Restore" : step === "welcome" ? "Step 1 of 2 · About you" : "Step 2 of 2 · Backup"}
        </div>

        {step === "welcome" && (
          <>
            <h1>Keep a verifiable history of your research</h1>
            <ul className="intro">
              <li>
                <b>Add steps</b> as you go — ideas, hypotheses, experiments, code, figures, papers — and link
                each one to the earlier steps it builds on.
              </li>
              <li>
                <b>Every step gets a date stamp automatically</b>, so you can later show it existed by that date and
                hasn't been changed since.
              </li>
              <li data-testid="home-note-setup">{HOME_NOTE}</li>
            </ul>
            <form onSubmit={start}>
              <label>
                Your name (or pen name)
                <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Name or pen name" required />
                <span className="note">Shown on what you share, as your own statement.</span>
              </label>
              <label>
                What research are you recording?
                <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="e.g. FSF" />
              </label>
              {error && <p className="error">{error}</p>}
              <button className="primary big" disabled={busy || !label.trim()}>
                {busy ? "Setting up…" : "Start"}
              </button>
              <p className="note">
                This also creates a signing key kept in this Mac's Keychain. It shows that all steps came from the same
                key — not who you are.
              </p>
            </form>
            <p className="small center">
              Already used this app on another Mac?{" "}
              <button type="button" className="link" onClick={() => setStep("restore")}>
                Restore from a backup
              </button>
            </p>
          </>
        )}

        {step === "backup" && (
          <>
            <h1>Turn on automatic backup</h1>
            <p>
              Your research lives on this Mac. If the Mac is lost or breaks, a backup is what brings it back — the
              stamps alone can't. Choose a folder once; after that every new step is backed up automatically.
            </p>
            <BackupSetup onDone={onDone} />
            <p className="small center">
              <button type="button" className="link muted" onClick={onDone}>
                Skip for now
              </button>{" "}
              <span className="muted">(you can turn it on later from the backup button at the top)</span>
            </p>
          </>
        )}

        {step === "restore" && (
          <>
            <h1>Restore your research</h1>
            <p>
              Choose a backup file (<span className="mono">.rprovbackup</span>) and enter its password. Your steps,
              files, stamps and signing key come back exactly as they were.
            </p>
            <RestoreForm onDone={onDone} />
            <p className="small center">
              <button type="button" className="link" onClick={() => setStep("welcome")}>
                Back
              </button>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
