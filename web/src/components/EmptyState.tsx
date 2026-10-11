import type { Space } from "../api";
import { HOME_NOTE } from "../labels";
import type { BackupStatus } from "../types";

export const STEP_TYPES: { type: string; label: string; hint: string }[] = [
  { type: "idea", label: "Idea", hint: "a first thought or intuition" },
  { type: "claim", label: "Hypothesis", hint: "a claim you want to test" },
  { type: "note", label: "Note", hint: "reading notes, observations" },
  { type: "experiment", label: "Experiment", hint: "a run, a trial, its outcome" },
  { type: "code", label: "Code", hint: "a script or a commit" },
  { type: "dataset", label: "Data", hint: "results, measurements" },
  { type: "figure", label: "Figure", hint: "a plot or diagram" },
  { type: "document", label: "Document", hint: "a draft, a formula, a write-up" },
  { type: "publication", label: "Paper", hint: "a preprint or publication" },
];

// Shown instead of an empty graph: what this is, and one obvious first action.
export function EmptyState({
  projectTitle,
  backup,
  onAdd,
  onBackup,
  space,
  onSample,
}: {
  projectTitle: string;
  backup: BackupStatus | null;
  onAdd: (type?: string) => void;
  onBackup: () => void;
  space: Space;
  onSample: () => void;
}) {
  const practice = space === "practice";
  return (
    <div className="empty-state" data-testid="empty-state">
      <div className="card wide">
        {practice ? (
          <>
            <h1>Try it out here</h1>
            <p className="lead">
              This is the practice space: add a few steps, link them, share them — nothing here goes into your real
              record.{" "}
              <button className="link" onClick={onSample} data-testid="practice-sample">
                Or fill it with sample research to look around
              </button>
            </p>
          </>
        ) : (
          <>
            <h1>Record the first step of {projectTitle}</h1>
            <p className="lead">Build a verifiable history of how this research develops.</p>
          </>
        )}
        <div className="field-label">What are you adding?</div>
        <div className="type-grid">
          {STEP_TYPES.map((t) => (
            <button key={t.type} className="type-card" onClick={() => onAdd(t.type)} data-testid={`start-${t.type}`}>
              <b>{t.label}</b>
              <span className="muted small">{t.hint}</span>
            </button>
          ))}
        </div>
        <ol className="how">
          <li>
            <b>Add a step</b> — write it down or attach files.
          </li>
          <li>
            <b>Link it to earlier steps</b> — “new version of”, “grew out of”, or “builds on”.
          </li>
          <li>
            <b>Date stamps happen automatically</b> — nothing to do.
          </li>
          <li>
            <b>Watch the history grow</b> — and share it as a report anyone can check.
          </li>
        </ol>
        <p className="note" data-testid="home-note-empty">{HOME_NOTE}</p>
        {!practice && backup?.state !== "ok" && (
          <div className="callout">
            {backup?.state === "same-disk" ? (
              <>Your backup folder is on this Mac only, so it won't help if the Mac is lost.</>
            ) : (
              <>Automatic backup is not on yet — if this Mac is lost or breaks, your research would be lost too.</>
            )}{" "}
            <button className="secondary small" onClick={onBackup}>
              Set up backup
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
