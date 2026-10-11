import { useState } from "react";
import { api } from "../api";
import type { GraphNode, RecordDetail } from "../types";

const REL_LABELS: Record<string, string> = { revises: "revises", derived_from: "derived from", uses: "uses" };

interface Props {
  detail: RecordDetail;
  node: GraphNode | undefined;
  entries: GraphNode[];
  relationTypes: string[];
  onChanged: () => void;
}

type Mode = null | "relation" | "statement" | "retract";

// Append-only actions: each one adds a new, separately signed and time-stamped record.
export function LaterActions({ detail, node, entries, relationTypes, onChanged }: Props) {
  const [mode, setMode] = useState<Mode>(null);
  const [rel, setRel] = useState(relationTypes[0] ?? "revises");
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [corrects, setCorrects] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (detail.kind !== "entry") return null;
  const older = entries.filter((e) => e.seq < detail.seq);
  const statements = detail.later.items.filter((l) => l.kind === "statement");

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setMode(null);
      setText("");
      setTarget("");
      setCorrects("");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="later-actions" data-testid="later-actions">
      <div className="row">
        <button className="secondary small" onClick={() => setMode(mode === "relation" ? null : "relation")}
          disabled={older.length === 0}>
          Add relation…
        </button>
        <button className="secondary small" disabled={busy}
          onClick={() => run(() => api.createMilestone(detail.id, node?.milestone ? "unset" : "set"))}>
          {node?.milestone ? "Unmark key step" : "Mark as key step"}
        </button>
        <button className="secondary small" onClick={() => setMode(mode === "statement" ? null : "statement")}>
          Add statement…
        </button>
        {!detail.retracted && (
          <button className="secondary small danger" onClick={() => setMode(mode === "retract" ? null : "retract")}>
            Retract…
          </button>
        )}
      </div>
      {mode === "relation" && (
        <div className="group">
          <div className="row">
            <span className="muted">this step</span>
            <select value={rel} onChange={(e) => setRel(e.target.value)}>
              {relationTypes.map((t) => (
                <option key={t} value={t}>{REL_LABELS[t] ?? t}</option>
              ))}
            </select>
            <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Earlier step">
              <option value="">choose an earlier step…</option>
              {[...older].reverse().map((e) => (
                <option key={e.id} value={e.id}>#{e.seq} {e.title}</option>
              ))}
            </select>
          </div>
          <textarea placeholder="Why? (optional, shown as an author statement)" value={text}
            onChange={(e) => setText(e.target.value)} rows={2} />
          <button className="primary small" disabled={busy || !target}
            onClick={() => run(() => api.createLink({ from: detail.id, to: target, rel, statement: text || undefined }))}>
            Add relation
          </button>
        </div>
      )}
      {mode === "statement" && (
        <div className="group">
          <textarea placeholder="Additional note or correction" value={text} onChange={(e) => setText(e.target.value)} rows={3} />
          {statements.length > 0 && (
            <select value={corrects} onChange={(e) => setCorrects(e.target.value)} aria-label="Corrects">
              <option value="">(not a correction)</option>
              {statements.map((s) => (
                <option key={s.record_id} value={s.record_id}>corrects: {s.text?.slice(0, 60)}</option>
              ))}
            </select>
          )}
          <button className="primary small" disabled={busy || !text.trim()}
            onClick={() => run(() => api.createStatement(detail.id, text, corrects || undefined))}>
            Add statement
          </button>
        </div>
      )}
      {mode === "retract" && (
        <div className="group">
          <textarea placeholder="Reason for retracting (shown as an author statement)" value={text}
            onChange={(e) => setText(e.target.value)} rows={2} />
          <button className="primary small" disabled={busy || !text.trim()}
            onClick={() => run(() => api.createRetraction(detail.id, text))}>
            Retract this entry
          </button>
        </div>
      )}
      {error && <p className="error small">{error}</p>}
      <p className="note">Each action is added as a new entry with its own signature and stamps. Nothing already saved is changed.</p>
    </section>
  );
}

export function WithdrawRelation({ from, to, rel, onChanged }: { from: string; to: string; rel: string; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <button className="link small" disabled={busy} title="Adds a new record that withdraws this relation"
      onClick={async () => {
        if (!window.confirm("Withdraw this relation? A new record is added; the original stays visible as withdrawn.")) return;
        setBusy(true);
        try {
          await api.createLink({ from, to, rel, op: "withdraw" });
          onChanged();
        } finally {
          setBusy(false);
        }
      }}>
      withdraw
    </button>
  );
}
