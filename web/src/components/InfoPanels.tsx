import { useState } from "react";
import type { Status } from "../types";
import { timeAgo } from "../util";

// Graph legend, on request instead of always on screen.
export function LegendButton() {
  const [open, setOpen] = useState(false);
  return (
    <div className="legend-wrap">
      <button className="link small" onClick={() => setOpen(!open)} aria-expanded={open} data-testid="legend-button">
        How to read the graph
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Legend" data-testid="legend">
          <div className="popover-head">
            <b>How to read the graph</b>
            <button className="link" onClick={() => setOpen(false)} aria-label="Close legend">
              ✕
            </button>
          </div>
          <p className="small">Each box is a research step, left to right in the order you added them. Arrows point from an earlier step to a later one.</p>
          <ul className="legend-list small">
            <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" /></svg> <span><b>revises</b> — a new version of</span></li>
            <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" strokeDasharray="7 4" /></svg> <span><b>derived from</b> — grew out of</span></li>
            <li><svg width="40" height="8"><line x1="0" y1="4" x2="40" y2="4" stroke="#3b4a63" strokeWidth="2" strokeDasharray="2 4" /></svg> <span><b>uses</b> — builds on</span></li>
            <li><span className="star">★</span> <span>gold border — a milestone you marked</span></li>
            <li><span className="proof-icon on">T</span> <span><b>Third-party timestamp</b> (FreeTSA) — arrives in seconds; shows the step existed at that time</span></li>
            <li><span className="proof-icon pending">B</span> <span><b>Bitcoin anchor</b> — independent of any company; dashed while waiting, confirms within a few hours</span></li>
            <li><span className="proof-icon off">T</span> <span>empty — no timestamp yet (the app keeps trying)</span></li>
          </ul>
          <p className="note">“added …” on an arrow means you linked the steps later. Grey arrows were withdrawn.</p>
        </div>
      )}
    </div>
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
        <h3>Your research stays on this Mac</h3>
        <p className="small">
          Everything you add — text, files, links between steps — is stored here: <span className="mono">{status.data_dir}</span>.
          The page you are looking at is served by this Mac to itself; nobody else can open it.
        </p>
        <h3>Backups bring it back</h3>
        {b?.configured ? (
          <p className="small">
            Automatic encrypted backups go to <span className="mono">{b.location}</span> ({b.where?.label}); last one{" "}
            {timeAgo(b.last_backup)}. {b.where?.warning}
          </p>
        ) : (
          <p className="small">
            <b>Not set up yet.</b> Without a backup, a lost or broken Mac means lost research.{" "}
            <button className="link" onClick={onBackup}>Set up backup</button>
          </p>
        )}
        <h3>Timestamps prove time — they don't store anything</h3>
        <p className="small">
          FreeTSA and the Bitcoin network only receive a fingerprint (hash) of each step. From a fingerprint nobody can
          read or rebuild your content — so they also can't give it back. That is what backups are for.
        </p>
        <h3>If this Mac is lost</h3>
        <p className="small">
          Install the app on the new Mac and choose <b>Restore from a backup</b> on the first screen. You need the backup
          file and its password. Your steps, files, timestamps and signing key come back as they were.
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
          <dt>Timestamp services</dt>
          <dd>Third-party timestamp: {status.providers.tsa ?? "off"} · Bitcoin anchor: {status.providers.btc ?? "not enabled"}</dd>
        </dl>
        <p className="small">
          The signing key is part of every full backup. To keep a separate copy of just the key:{" "}
          <button className="link" onClick={onKeyBackup}>Back up signing key only…</button>
        </p>
      </div>
    </div>
  );
}
