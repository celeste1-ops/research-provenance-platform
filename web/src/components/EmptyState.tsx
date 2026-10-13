import type { Space } from "../api";
import { homeNote, typeLabel } from "../labels";
import type { BackupStatus } from "../types";
import { dev } from "../device";
import { t, tx } from "../i18n";

function stepTypes(): { type: string; label: string; hint: string }[] {
  return [
    { type: "idea", label: typeLabel("idea"), hint: t("a first thought or intuition") },
    { type: "claim", label: t("Hypothesis"), hint: t("a claim you want to test") },
    { type: "note", label: typeLabel("note"), hint: t("reading notes, observations") },
    { type: "experiment", label: typeLabel("experiment"), hint: t("a run, a trial, its outcome") },
    { type: "code", label: typeLabel("code"), hint: t("a script or a commit") },
    { type: "dataset", label: typeLabel("dataset"), hint: t("results, measurements") },
    { type: "figure", label: typeLabel("figure"), hint: t("a plot or diagram") },
    { type: "document", label: typeLabel("document"), hint: t("a draft, a formula, a write-up") },
    { type: "publication", label: typeLabel("publication"), hint: t("a preprint or publication") },
  ];
}

const bold = { b: (s: string) => <b>{s}</b> };

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
            <h1>{t("Try it out here")}</h1>
            <p className="lead">
              {t("This is the practice space: add a few steps, link them, share them — nothing here goes into your real record.")}{" "}
              <button className="link" onClick={onSample} data-testid="practice-sample">
                {t("Or look at the finished example first")}
              </button>
            </p>
          </>
        ) : (
          <>
            <h1>{t("Record the first step of {project}", { project: projectTitle })}</h1>
            <p className="lead">
              {t("Build a verifiable history of how this research develops.")}{" "}
              <button className="link" onClick={onSample} data-testid="real-sample">
                {t("Not sure how? Look at a finished example")}
              </button>
            </p>
          </>
        )}
        <div className="field-label">{t("What are you adding?")}</div>
        <div className="type-grid">
          {stepTypes().map((s) => (
            <button key={s.type} className="type-card" onClick={() => onAdd(s.type)} data-testid={`start-${s.type}`}>
              <b>{s.label}</b>
              <span className="muted small">{s.hint}</span>
            </button>
          ))}
        </div>
        <ol className="how">
          <li>{tx("<b>Add a step</b> — write it down or attach files.", bold)}</li>
          <li>{tx("<b>Link it to earlier steps</b> — “new version of”, “grew out of”, or “builds on”.", bold)}</li>
          <li>{tx("<b>Date stamps happen automatically</b> — nothing to do.", bold)}</li>
          <li>{tx("<b>Watch the history grow</b> — and share it as a report anyone can check.", bold)}</li>
        </ol>
        <p className="note" data-testid="home-note-empty">{homeNote()}</p>
        {!practice && backup?.state !== "ok" && (
          <div className="callout">
            {backup?.state === "same-disk"
              ? t("Your backup folder is on this {device} only, so it won't help if the {device} is lost.", { device: dev() })
              : backup?.state === "paused"
                ? t("Automatic backup is paused after restoring — confirm the folder to resume it.")
                : t("Automatic backup is not on yet — if this {device} is lost or breaks, your research would be lost too.", { device: dev() })}{" "}
            <button className="secondary small" onClick={onBackup}>
              {backup?.state === "paused" ? t("Review backup") : t("Set up backup")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
