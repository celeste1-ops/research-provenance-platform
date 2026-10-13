import { useEffect, useState } from "react";
import { t } from "../i18n";
import type { SampleInfo } from "../types";

// A tour of the FSF sample research (DECISIONS D-059): each stop opens the part of the app that
// shows one thing it does, on the sample's own steps.

export type TourAction =
  | { view: "steps" | "graph" | "story" }
  | { select: string }
  | { keyOnly: true }
  | { project: string }
  | { export: true };

interface Stop {
  key: string;
  label: () => string;
  text: () => string;
  action: TourAction;
}

const STOPS: Stop[] = [
  {
    key: "steps",
    label: () => t("Step cards"),
    text: () => t("Each card says what a step holds and which earlier steps it came from; the oldest is at the top. Click a card to see all of it."),
    action: { view: "steps" },
  },
  {
    key: "turn",
    label: () => t("A turning point"),
    text: () => t("Experiment 1 did not fit hypothesis H1, so H1′ revised it. Both stay in the record, linked: the change of mind is part of the history."),
    action: { select: "h1b" },
  },
  {
    key: "map",
    label: () => t("The map"),
    text: () => t("Time runs from left to right, one row per kind of step. Point at a step to see its lines and what it says."),
    action: { view: "graph" },
  },
  {
    key: "git",
    label: () => t("Code from git"),
    text: () => t("Each commit became a step by itself, with a copy of the code; a tagged commit is a key step. Earlier commits came in as one history step."),
    action: { select: "solver21" },
  },
  {
    key: "files",
    label: () => t("Pictures and data"),
    text: () => t("Pictures and text files (data, code, notes) show in place; other files, such as a PDF or a zip, download."),
    action: { select: "fig2" },
  },
  {
    key: "later",
    label: () => t("Added later"),
    text: () => t("A clarification, then its correction, and a key-step mark added afterwards: later additions are records of their own, dated when they were added."),
    action: { select: "exp1" },
  },
  {
    key: "withdrawn",
    label: () => t("Withdrawn, not deleted"),
    text: () => t("The lattice idea was withdrawn, with the reason. It stays in sight, crossed out — nothing is ever deleted. The draft that built on it withdrew that link."),
    action: { select: "lattice" },
  },
  {
    key: "older",
    label: () => t("Older material"),
    text: () => t("A notebook page from 2025, added now: the earlier date is the author's own statement; the date stamp shows when it was added."),
    action: { select: "intuition" },
  },
  {
    key: "key",
    label: () => t("Key steps only"),
    text: () => t("Five key steps tell the research in brief; between them it says how many steps were left out."),
    action: { keyOnly: true },
  },
  {
    key: "story",
    label: () => t("The story"),
    text: () => t("The research told in sentences, made from the records alone, without AI. Click a #number to check a sentence."),
    action: { view: "story" },
  },
  {
    key: "share",
    label: () => t("Share it"),
    text: () => t("Make a report anyone can open and check with the verify.py that comes with it, choosing for each step how much to show."),
    action: { export: true },
  },
  {
    key: "projects",
    label: () => t("A second project"),
    text: () => t("The list at the top switches between projects: here the flow channel setup, recorded on its own."),
    action: { project: "side" },
  },
];

const HIDE_KEY = "rprov-tour-hidden";

export function SampleTour({ sample, projectId, onAction, start = 0, onStarted }: {
  sample: SampleInfo;
  projectId: string; // the project open now: the bar says which of the sample's two it is
  onAction: (action: TourAction) => void;
  start?: number; // "See the example" (D-062): when this is set, the tour shows and opens its first stop
  onStarted?: () => void;
}) {
  const [active, setActive] = useState<string | null>(null);
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem(HIDE_KEY) === "1";
    } catch {
      return false;
    }
  });

  function hide(next: boolean) {
    setHidden(next);
    try {
      window.localStorage.setItem(HIDE_KEY, next ? "1" : "0");
    } catch {
      /* storage unavailable: for this visit */
    }
  }

  function go(stop: Stop) {
    setActive(stop.key);
    const a = stop.action;
    if ("select" in a) onAction({ select: sample.ids[a.select] ?? a.select });
    else if ("project" in a) onAction({ project: sample.projects[a.project] ?? a.project });
    else onAction(a);
  }

  // Asked for from Settings: shown even if it was hidden before, from the first stop.
  useEffect(() => {
    if (!start) return;
    hide(false);
    go(STOPS[0]);
    onStarted?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start]);

  if (hidden) {
    return (
      <div className="sample-tour folded" data-testid="sample-tour">
        <button className="link small" onClick={() => hide(false)} data-testid="sample-tour-show">
          {t("Show the tour of the sample research")}
        </button>
      </div>
    );
  }
  const current = STOPS.find((s) => s.key === active);
  // "FSF" names the whole sample research; it has two projects. Say which one is open, so the second
  // (the flow channel setup) is not taken for a different research.
  const where = projectId === sample.projects.side
    ? t("Project 2 of 2: the flow channel setup — the apparatus built for the FSF experiments, recorded as a project of its own.")
    : projectId === sample.projects.main
      ? t("Project 1 of 2: the FSF research itself.")
      : null;
  return (
    <div className="sample-tour" data-testid="sample-tour">
      <div className="sample-tour-head">
        <b>{t("Sample research: FSF (fictional)")}</b>
        <span className="muted small">{t("Click a stop to see what the app does with it. Change anything you like: this is only the example.")}</span>
        <span className="spacer" />
        <button className="link small" onClick={() => hide(true)} data-testid="sample-tour-hide">{t("Hide")}</button>
      </div>
      {where && <p className="sample-tour-where small" data-testid="sample-tour-where">{where}</p>}
      <ol className="sample-tour-stops">
        {STOPS.map((s, i) => (
          <li key={s.key}>
            <button className={s.key === active ? "on" : ""} onClick={() => go(s)} data-testid={`tour-${s.key}`}>
              <span className="tour-no">{i + 1}</span> {s.label()}
            </button>
          </li>
        ))}
      </ol>
      {current && <p className="sample-tour-text small" data-testid="sample-tour-text">{current.text()}</p>}
    </div>
  );
}
