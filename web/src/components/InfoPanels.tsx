import type { Status } from "../types";
import { timeAgo } from "../util";
import { dev } from "../device";
import { t, tx } from "../i18n";

const bold = { b: (s: string) => <b>{s}</b> };
const boldMono = { b: (s: string) => <b>{s}</b>, mono: (s: string) => <span className="mono">{s}</span> };

// How to read the map: lines, star and the two stamp icons. Shown behind the "?" next to Map.
export function Legend() {
  return (
    <span className="legend" data-testid="legend">
      <b>{t("How to read the map")}</b>
      <span className="block small">
        {t("Each box is a step, left to right in the order you added them. Arrows point from an earlier step to a later one.")}
      </span>
      <ul className="legend-list small">
        <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" /></svg> <span>{tx("<b>revises</b> — a new version of", bold)}</span></li>
        <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" strokeDasharray="7 4" /></svg> <span>{tx("<b>derived from</b> — grew out of", bold)}</span></li>
        <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" strokeDasharray="2 4" /></svg> <span>{tx("<b>uses</b> — builds on", bold)}</span></li>
        <li><span className="star">★</span> <span>{t("gold border — a key step you marked")}</span></li>
        <li><span className="proof-icon on">D</span> <span>{tx("<b>Date stamp</b> — arrives in seconds; shows the step existed at that time", bold)}</span></li>
        <li><span className="proof-icon pending">P</span> <span>{tx("<b>Public stamp</b> (Bitcoin) — dashed while waiting, done within a few hours", bold)}</span></li>
        <li><span className="proof-icon off">D</span> <span>{t("empty — no stamp yet (the app keeps trying)")}</span></li>
      </ul>
      <span className="block note">{t("“added …” on an arrow means you linked the steps later. Grey arrows were withdrawn.")}</span>
    </span>
  );
}

export function WhereIsMyData({ status, onClose, onBackup }: { status: Status; onClose: () => void; onBackup: () => void }) {
  const b = status.backup;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Where is my data?")}>
      <div className="modal" data-testid="where-is-my-data">
        <div className="modal-head">
          <h2>{t("Where is my data?")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <h3>{t("Your research stays on this {device}", { device: dev() })}</h3>
        {status.space === "practice" ? (
          <p className="small">
            {tx("You are in the <b>practice space</b>. It is kept apart from your real record, in <mono>{dir}</mono>, with its own signing key. It is never backed up and can be started over from Settings.", boldMono, { dir: status.data_dir })}
          </p>
        ) : (
          <p className="small">
            {tx("Everything you add — text, files, links between steps — is stored here: <mono>{dir}</mono>. The page you are looking at is served by this {device} to itself; nobody else can open it. Practice steps are kept apart, in <mono>{practice}</mono>.", boldMono, { dir: status.data_dir, device: dev(), practice: status.practice_dir })}
          </p>
        )}
        <h3>{status.space === "practice" ? t("Backups bring it back (for your real record)") : t("Backups bring it back")}</h3>
        {b?.configured ? (
          <p className="small">
            {tx("Automatic encrypted backups go to <mono>{folder}</mono> ({where}); last one {when}.", boldMono, { folder: b.location ?? "", where: b.where?.label ?? "", when: timeAgo(b.last_backup) })}{" "}
            {b.where?.warning}
          </p>
        ) : (
          <p className="small">
            {tx("<b>Not set up yet.</b> Without a backup, a lost or broken {device} means lost research.", bold, { device: dev() })}{" "}
            <button className="link" onClick={onBackup}>{t("Set up backup")}</button>
          </p>
        )}
        <h3>{t("Stamps prove time — they don't store anything")}</h3>
        <p className="small">
          {t("The date stamp services (FreeTSA, or DigiCert when FreeTSA can't be reached) and the Bitcoin network only receive a fingerprint (hash) of each step. From a fingerprint nobody can read or rebuild your content — so they can't give it back either, not even through Bitcoin. Only a backup can bring your files back.")}
        </p>
        <h3>{t("If this {device} is lost", { device: dev() })}</h3>
        <p className="small">
          {tx("Install the app on the new {device} and choose <b>Restore from a backup</b> on the first screen. You need the backup file and its password. Your steps, files, stamps and signing key come back as they were.", bold, { device: dev() })}
        </p>
      </div>
    </div>
  );
}

export function TechnicalDetails({ status, onClose, onKeyBackup }: { status: Status; onClose: () => void; onKeyBackup: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Technical details")}>
      <div className="modal" data-testid="technical-details">
        <div className="modal-head">
          <h2>{t("Technical details")}</h2>
          <button className="link" onClick={onClose} aria-label={t("Close")}>✕</button>
        </div>
        <dl>
          <dt>{t("Author label")}</dt>
          <dd>{status.author_label} <span className="muted small">{t("(self-declared)")}</span></dd>
          <dt>{t("Signing key")}</dt>
          <dd className="mono">{status.public_key}</dd>
          <dt>{t("Installation")}</dt>
          <dd className="mono">{status.installation}</dd>
          <dt>{t("Records in the log")}</dt>
          <dd>
            {status.record_count} —{" "}
            {status.entry_count === 1
              ? t("1 research step, plus the first “genesis” record that holds your public key, plus later additions (links, notes, milestones, retractions)")
              : t("{n} research steps, plus the first “genesis” record that holds your public key, plus later additions (links, notes, milestones, retractions)", { n: status.entry_count })}
          </dd>
          <dt>{t("Data folder")}</dt>
          <dd className="mono">{status.data_dir}</dd>
          <dt>{t("Stamp services")}</dt>
          <dd>
            {t("Date stamp (third-party timestamp):")} {status.providers.tsa ?? t("off")} ·{" "}
            {t("Public stamp (Bitcoin anchor):")} {status.providers.btc ?? t("off")}
          </dd>
        </dl>
        <p className="small">
          {t("The signing key is part of every full backup. To keep a separate copy of just the key:")}{" "}
          <button className="link" onClick={onKeyBackup}>{t("Back up signing key only…")}</button>
        </p>
      </div>
    </div>
  );
}
