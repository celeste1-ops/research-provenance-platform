import { help, STAMP_LETTERS, stampText } from "../labels";
import { t } from "../i18n";
import type { ProofStatus } from "../types";
import { Help } from "./Help";

// Small icon used on graph nodes: D = date stamp, P = public stamp (Bitcoin).
export function ProofIcon({ proof }: { proof: ProofStatus }) {
  const cls =
    proof.state === "confirmed" ? "on" : proof.state === "pending" ? "pending" : "off";
  return (
    <span className={`proof-icon ${cls}`} title={stampText(proof)} data-proof={proof.kind} data-state={proof.state}>
      {STAMP_LETTERS[proof.kind]}
    </span>
  );
}

// One line of text for one kind of proof. The two kinds are never merged.
export function ProofLine({ proof }: { proof: ProofStatus }) {
  return (
    <div className={`proof-line state-${proof.state}`} data-proof={proof.kind}>
      <ProofIcon proof={proof} />
      <span>{stampText(proof)}</span>
      <Help id={`stamp-${proof.kind}`} label={proof.kind === "tsa" ? t("a date stamp") : t("a public stamp")}>
        {proof.kind === "tsa" ? help("dateStamp") : help("publicStamp")}
      </Help>
      {proof.time && <span className="mono time">{proof.time}</span>}
      {proof.error && <span className="muted small"> — {t("last error:")} {proof.error}</span>}
    </div>
  );
}
