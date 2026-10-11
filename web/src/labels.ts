import { dev } from "./device";
import { t } from "./i18n";
import type { ProofStatus } from "./types";

// Plain words used everywhere in the app (DECISIONS D-034, D-037). Reports and verify.py
// keep the formal names; the "?" explanations name both so the two can be matched up.

const TYPE_EN: Record<string, string> = {
  idea: "Idea",
  note: "Note",
  claim: "Hypothesis / claim",
  document: "Document",
  code: "Code",
  experiment: "Experiment",
  dataset: "Data",
  figure: "Figure",
  publication: "Paper",
};

/** The name of a kind of step, in the current language. */
export function typeLabel(kind: string): string {
  switch (kind) {
    case "idea":
      return t("Idea");
    case "note":
      return t("Note");
    case "claim":
      return t("Hypothesis / claim");
    case "document":
      return t("Document");
    case "code":
      return t("Code");
    case "experiment":
      return t("Experiment");
    case "dataset":
      return t("Data");
    case "figure":
      return t("Figure");
    case "publication":
      return t("Paper");
    default:
      return kind;
  }
}

export const TYPE_KINDS = Object.keys(TYPE_EN);

export function stampName(kind: "tsa" | "btc"): string {
  return kind === "tsa" ? t("Date stamp") : t("Public stamp");
}

export const STAMP_LETTERS = { tsa: "D", btc: "P" } as const;

// Short status word for one stamp, without the name: "✓", "waiting", "done", "not yet", "off".
export function stampState(p: ProofStatus): string {
  if (p.state === "confirmed") return p.kind === "tsa" ? "✓" : t("done");
  if (p.state === "pending") return t("waiting");
  if (p.state === "not_enabled") return t("off");
  return p.retrying ? t("not yet (retrying)") : t("not yet");
}

// "Date stamp ✓", "Public stamp: waiting", … The two stamps are never merged.
export function stampText(p: ProofStatus): string {
  const s = stampState(p);
  return s === "✓" ? `${stampName(p.kind)} ✓` : t("{stamp}: {state}", { stamp: stampName(p.kind), state: s });
}

export function help(key: "addStep" | "list" | "keySteps" | "share" | "dateStamp" | "publicStamp"): string {
  switch (key) {
    case "addStep":
      return t("Write down one step of your research — an idea, a result, a file. It gets its date stamp within seconds.");
    case "list":
      return t("Every step and every later addition in the order you added them, with both stamps.");
    case "keySteps":
      return t("Show only the steps you marked as key steps, and how they lead to each other.");
    case "share":
      return t("Make a package anyone can check: a report plus a small checking program. You choose how much of each step it shows.");
    case "dateStamp":
      return t("An independent timestamp service (FreeTSA, or DigiCert when FreeTSA can't be reached) signs a fingerprint of the step within seconds. It shows the step existed at that time and has not changed since. Reports call it “Third-party timestamp”.");
    case "publicStamp":
      return t("The same fingerprint is also written into the public Bitcoin blockchain, which anyone can check without trusting any company. It takes a few hours. Reports call it “Bitcoin anchor”.");
  }
}

export function homeNote(): string {
  return t("Your notes stay on this {device}. Only a fingerprint is sent out to get a date stamp. Backups let you get everything back if this {device} is lost.", { device: dev() });
}
