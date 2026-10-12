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

// One colour per kind of step, the same in every view, so a kind is recognised before it is read.
const TYPE_COLORS: Record<string, [string, string]> = {
  idea: ["#9a5b00", "#fdf0d0"],
  note: ["#475569", "#edf1f6"],
  claim: ["#6d28d9", "#efe8fe"],
  document: ["#1d4ed8", "#e2ebff"],
  code: ["#0f766e", "#d6f4ee"],
  experiment: ["#c2410c", "#ffeadb"],
  dataset: ["#15803d", "#dcf4e3"],
  figure: ["#be185d", "#fde6f0"],
  publication: ["#4338ca", "#e6e7ff"],
};

/** The colours of a kind of step, as CSS variables: --type (text, lines) and --type-bg. */
export function typeStyle(kind: string): Record<string, string> {
  const [fg, bg] = TYPE_COLORS[kind] ?? TYPE_COLORS.note;
  return { "--type": fg, "--type-bg": bg };
}

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

export function help(key: "addStep" | "list" | "story" | "keySteps" | "share" | "dateStamp" | "publicStamp"): string {
  switch (key) {
    case "addStep":
      return t("Write down one step of your research — an idea, a result, a file. It gets its date stamp within seconds.");
    case "list":
      return t("Every step and every later addition in the order you added them, with both stamps.");
    case "story":
      return t("Your research told in sentences, written from the steps with fixed wording — no AI. Each paragraph names the step it comes from; your own reasons and notes are highlighted. It also goes into the report you share.");
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

/** Where a step's outside reference can be opened: a DOI, a repository, a web address. */
export function referenceHref(ext: { commit?: string; repo_url?: string; doi?: string; url?: string } | null | undefined):
  string | null {
  if (!ext) return null;
  const web = (u?: string) => (u && /^https?:\/\//i.test(u) ? u : null);
  if (ext.doi) return `https://doi.org/${ext.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")}`;
  return web(ext.repo_url) ?? web(ext.url);
}

/** "The author says it is from 2025-09 (not verified)" — an earlier date for older material. */
export function claimedText(claimed: { date: string } | null | undefined): string | null {
  return claimed ? t("The author says it is from {date} — not verified", { date: claimed.date }) : null;
}
