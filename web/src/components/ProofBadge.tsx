import type { ProofStatus } from "../types";

// Small icon used on graph nodes: T = third-party timestamp, B = Bitcoin anchor.
export function ProofIcon({ proof }: { proof: ProofStatus }) {
  const letter = proof.kind === "tsa" ? "T" : "B";
  const cls =
    proof.state === "confirmed" ? "on" : proof.state === "pending" ? "pending" : "off";
  return (
    <span className={`proof-icon ${cls}`} title={proof.text} data-proof={proof.kind} data-state={proof.state}>
      {letter}
    </span>
  );
}

// One line of text for one kind of proof. The two kinds are never merged.
export function ProofLine({ proof }: { proof: ProofStatus }) {
  return (
    <div className={`proof-line state-${proof.state}`} data-proof={proof.kind}>
      <ProofIcon proof={proof} />
      <span>{proof.text}</span>
      {proof.time && <span className="mono time">{proof.time}</span>}
      {proof.error && <span className="muted small"> — last error: {proof.error}</span>}
    </div>
  );
}
