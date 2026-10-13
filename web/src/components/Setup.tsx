import { useState } from "react";
import { api } from "../api";
import { homeNote } from "../labels";
import { BackupSetup, RestoreForm } from "./BackupDialog";
import { dev, keychainName } from "../device";
import { lang, t, tx, type Lang } from "../i18n";
import { LangSwitch } from "./LangSwitch";

const bold = { b: (s: string) => <b>{s}</b> };

// First run: (1) your name + first project, (2) automatic backup. Or restore instead.
export function Setup({ onDone, onPractice, onSample, onLang }: {
  onDone: () => void;
  onPractice: () => void;
  onSample: () => void;
  onLang: (l: Lang) => void;
}) {
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
      await api.createProject(project.trim() || t("My research"));
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
        <div className="setup-head">
          <div className="steps-indicator small muted">
            {step === "restore" ? t("Restore") : step === "welcome" ? t("Step 1 of 2 · About you") : t("Step 2 of 2 · Backup")}
          </div>
          {step === "welcome" && <LangSwitch value={lang()} onChange={onLang} />}
        </div>

        {step === "welcome" && (
          <>
            <h1>{t("Keep a verifiable history of your research")}</h1>
            <ul className="intro">
              <li>
                {tx("<b>Add steps</b> as you go — ideas, hypotheses, experiments, code, figures, papers — and link each one to the earlier steps it builds on.", bold)}
              </li>
              <li>
                {tx("<b>Every step gets a date stamp automatically</b>, so you can later show it existed by that date and hasn't been changed since.", bold)}
              </li>
              <li data-testid="home-note-setup">{homeNote()}</li>
            </ul>
            <div className="sample-offer" data-testid="sample-offer">
              <div>
                <b>{t("See a finished example first")}</b>
                <p className="small muted">
                  {t("A fictional research project, FSF: 32 steps in two projects, using everything the app does, with a short tour. It opens in a space of its own, the example, so nothing goes into your real record or your practice.")}
                </p>
              </div>
              <button type="button" className="secondary" onClick={onSample} data-testid="setup-sample">
                {t("Open the example")}
              </button>
            </div>
            <form onSubmit={start}>
              <label>
                {t("Your name (or pen name)")}
                <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("Name or pen name")} required />
                <span className="note">{t("Shown on what you share, as your own statement.")}</span>
              </label>
              <label>
                {t("What research are you recording?")}
                <input value={project} onChange={(e) => setProject(e.target.value)} placeholder={t("e.g. FSF")} />
              </label>
              {error && <p className="error">{error}</p>}
              <button className="primary big" disabled={busy || !label.trim()}>
                {busy ? t("Setting up…") : t("Start")}
              </button>
              <p className="note">
                {t("This also creates a signing key kept in this {device}'s {keychain}. It shows that all steps came from the same key — not who you are.", { device: dev(), keychain: keychainName() })}
              </p>
            </form>
            <p className="small center">
              {t("Just want to try it first?")}{" "}
              <button type="button" className="link" onClick={onPractice} data-testid="setup-practice">
                {t("Open the practice space")}
              </button>{" "}
              <span className="muted">{t("— nothing there goes into your real record.")}</span>
            </p>
            <p className="small center">
              {t("Already used this app on another {device}?", { device: dev() })}{" "}
              <button type="button" className="link" onClick={() => setStep("restore")}>
                {t("Restore from a backup")}
              </button>
            </p>
          </>
        )}

        {step === "backup" && (
          <>
            <h1>{t("Turn on automatic backup")}</h1>
            <p>
              {t("Your research lives on this {device}. If the {device} is lost or breaks, a backup is what brings it back — the stamps alone can't. Choose a folder once; after that every new step is backed up automatically.", { device: dev() })}
            </p>
            <BackupSetup onDone={onDone} onSkip={onDone} />
          </>
        )}

        {step === "restore" && (
          <>
            <h1>{t("Restore your research")}</h1>
            <p>
              {tx("Choose a backup file (<mono>.rprovbackup</mono>) and enter its password. Your steps, files, stamps and signing key come back exactly as they were.", { mono: (s) => <span className="mono">{s}</span> })}
            </p>
            <RestoreForm onDone={onDone} />
            <p className="small center">
              <button type="button" className="link" onClick={() => setStep("welcome")}>
                {t("Back")}
              </button>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
