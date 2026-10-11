import { dev } from "./device";
import type { ProofStatus } from "./types";

// Plain words used everywhere in the app (DECISIONS D-034, D-037). Reports and verify.py
// keep the formal names; the "?" explanations name both so the two can be matched up.

export const TYPE_LABELS: Record<string, string> = {
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

export const STAMP_NAMES = { tsa: "Date stamp", btc: "Public stamp" } as const;
export const STAMP_LETTERS = { tsa: "D", btc: "P" } as const;

// Short status word for one stamp, without the name: "✓", "waiting", "done", "not yet", "off".
export function stampState(p: ProofStatus): string {
  if (p.state === "confirmed") return p.kind === "tsa" ? "✓" : "done";
  if (p.state === "pending") return "waiting";
  if (p.state === "not_enabled") return "off";
  return p.text.includes("retrying") ? "not yet (retrying)" : "not yet";
}

// "Date stamp ✓", "Public stamp: waiting", … The two stamps are never merged.
export function stampText(p: ProofStatus): string {
  const s = stampState(p);
  return s === "✓" ? `${STAMP_NAMES[p.kind]} ✓` : `${STAMP_NAMES[p.kind]}: ${s}`;
}

export const HELP = {
  addStep:
    "Write down one step of your research — an idea, a result, a file. It gets its date stamp within seconds.",
  list: "Every step and every later addition in the order you added them, with both stamps.",
  keySteps: "Show only the steps you marked as key steps, and how they lead to each other.",
  share:
    "Make a package anyone can check: a report plus a small checking program. You choose how much of each step it shows.",
  dateStamp:
    "An independent timestamp service (FreeTSA, or DigiCert when FreeTSA can't be reached) signs a fingerprint of the step within seconds. It shows the step existed at that time and has not changed since. Reports call it “Third-party timestamp”.",
  publicStamp:
    "The same fingerprint is also written into the public Bitcoin blockchain, which anyone can check without trusting any company. It takes a few hours. Reports call it “Bitcoin anchor”.",
} as const;

export function homeNote(): string {
  return `Your notes stay on this ${dev()}. Only a fingerprint is sent out to get a date stamp. Backups let you get everything back if this ${dev()} is lost.`;
}
