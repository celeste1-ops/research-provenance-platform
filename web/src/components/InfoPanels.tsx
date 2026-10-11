import type { Status } from "../types";
import { timeAgo } from "../util";
import { dev } from "../device";

// How to read the map: lines, star and the two stamp icons. Shown behind the "?" next to Map.
export function Legend() {
  return (
    <span className="legend" data-testid="legend">
      <b>How to read the map</b>
      <span className="block small">
        Each box is a step, left to right in the order you added them. Arrows point from an earlier step to a later one.
      </span>
      <ul className="legend-list small">
        <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" /></svg> <span><b>revises</b> — a new version of</span></li>
        <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" strokeDasharray="7 4" /></svg> <span><b>derived from</b> — grew out of</span></li>
        <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" strokeDasharray="2 4" /></svg> <span><b>uses</b> — builds on</span></li>
        <li><span className="star">★</span> <span>gold border — a key step you marked</span></li>
        <li><span className="proof-icon on">D</span> <span><b>Date stamp</b> — arrives in seconds; shows the step existed at that time</span></li>
        <li><span className="proof-icon pending">P</span> <span><b>Public stamp</b> (Bitcoin) — dashed while waiting, done within a few hours</span></li>
        <li><span className="proof-icon off">D</span> <span>empty — no stamp yet (the app keeps trying)</span></li>
      </ul>
      <span className="block note">“added …” on an arrow means you linked the steps later. Grey arrows were withdrawn.</span>
    </span>
  );
}

export function WhereIsMyData({ status, onClose, onBackup }: { status: Status; onClose: () => void; onBackup: () => void }) {
  const b = status.backup;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Where is my data?">
      <div className="modal" data-testid="where-is-my-data">
        <div className="modal-head">
          <h2>Where is my data?</h2>
          <button className="link" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <h3>Your research stays on this {dev()}</h3>
        {status.space === "practice" ? (
          <p className="small">
            You are in the <b>practice space</b>. It is kept apart from your real record, in{" "}
            <span className="mono">{status.data_dir}</span>, with its own signing key. It is never backed up and can
            be started over from Settings.
          </p>
        ) : (
          <p className="small">
            Everything you add — text, files, links between steps — is stored here:{" "}
            <span className="mono">{status.data_dir}</span>. The page you are looking at is served by this {dev()} to
            itself; nobody else can open it. Practice steps are kept apart, in{" "}
            <span className="mono">{status.practice_dir}</span>.
          </p>
        )}
        <h3>Backups bring it back{status.space === "practice" ? " (for your real record)" : ""}</h3>
        {b?.configured ? (
          <p className="small">
            Automatic encrypted backups go to <span className="mono">{b.location}</span> ({b.where?.label}); last one{" "}
            {timeAgo(b.last_backup)}. {b.where?.warning}
          </p>
        ) : (
          <p className="small">
            <b>Not set up yet.</b> Without a backup, a lost or broken {dev()} means lost research.{" "}
            <button className="link" onClick={onBackup}>Set up backup</button>
          </p>
        )}
        <h3>Stamps prove time — they don't store anything</h3>
        <p className="small">
          The date stamp service (FreeTSA) and the Bitcoin network only receive a fingerprint (hash) of each step. From a
          fingerprint nobody can read or rebuild your content — so they can't give it back either, not even through
          Bitcoin. Only a backup can bring your files back.
        </p>
        <h3>If this {dev()} is lost</h3>
        <p className="small">
          Install the app on the new {dev()} and choose <b>Restore from a backup</b> on the first screen. You need the backup
          file and its password. Your steps, files, stamps and signing key come back as they were.
        </p>
      </div>
    </div>
  );
}

export function TechnicalDetails({ status, onClose, onKeyBackup }: { status: Status; onClose: () => void; onKeyBackup: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Technical details">
      <div className="modal" data-testid="technical-details">
        <div className="modal-head">
          <h2>Technical details</h2>
          <button className="link" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <dl>
          <dt>Author label</dt>
          <dd>{status.author_label} <span className="muted small">(self-declared)</span></dd>
          <dt>Signing key</dt>
          <dd className="mono">{status.public_key}</dd>
          <dt>Installation</dt>
          <dd className="mono">{status.installation}</dd>
          <dt>Records in the log</dt>
          <dd>
            {status.record_count} — {status.entry_count} research {status.entry_count === 1 ? "step" : "steps"}, plus
            the first “genesis” record that holds your public key, plus later additions (links, notes, milestones,
            retractions)
          </dd>
          <dt>Data folder</dt>
          <dd className="mono">{status.data_dir}</dd>
          <dt>Stamp services</dt>
          <dd>
            Date stamp (third-party timestamp): {status.providers.tsa ?? "off"} · Public stamp (Bitcoin anchor):{" "}
            {status.providers.btc ?? "off"}
          </dd>
        </dl>
        <p className="small">
          The signing key is part of every full backup. To keep a separate copy of just the key:{" "}
          <button className="link" onClick={onKeyBackup}>Back up signing key only…</button>
        </p>
      </div>
    </div>
  );
}
