import { useState } from "react";
import { api, type Space } from "../api";
import type { GraphNode, RecordDetail } from "../types";
import { ConfirmRealModal, type SummaryItem } from "./Confirm";
import { t } from "../i18n";
import { relLabel } from "./Timeline";

interface Props {
  detail: RecordDetail;
  node: GraphNode | undefined;
  entries: GraphNode[];
  relationTypes: string[];
  onChanged: () => void;
  space: Space;
}

interface Pending {
  title: string;
  items: SummaryItem[];
  action: () => Promise<unknown>;
}

type Mode = null | "relation" | "statement" | "retract";

// Append-only actions: each one adds a new, separately signed and time-stamped record.
export function LaterActions({ detail, node, entries, relationTypes, onChanged, space }: Props) {
  const [pending, setPending] = useState<Pending | null>(null);
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

  // In the real record every action is permanent, so it is confirmed first; practice runs directly.
  function run(fn: () => Promise<unknown>, title: string, items: SummaryItem[] = []) {
    setError(null);
    if (space === "practice") void execute(fn);
    else setPending({ title, items, action: fn });
  }

  async function execute(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setPending(null);
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
          {t("Add relation…")}
        </button>
        <button className="secondary small" disabled={busy}
          onClick={() =>
            run(
              () => api.createMilestone(detail.id, node?.milestone ? "unset" : "set"),
              node?.milestone
                ? t("Unmark “{title}” as a key step?", { title: detail.verified.title })
                : t("Mark “{title}” as a key step?", { title: detail.verified.title }),
            )
          }>
          {node?.milestone ? t("Unmark key step") : t("Mark as key step")}
        </button>
        <button className="secondary small" onClick={() => setMode(mode === "statement" ? null : "statement")}>
          {t("Add statement…")}
        </button>
        {!detail.retracted && (
          <button className="secondary small danger" onClick={() => setMode(mode === "retract" ? null : "retract")}>
            {t("Retract…")}
          </button>
        )}
      </div>
      {mode === "relation" && (
        <div className="group">
          <div className="row">
            <span className="muted">{t("this step")}</span>
            <select value={rel} onChange={(e) => setRel(e.target.value)}>
              {relationTypes.map((r) => (
                <option key={r} value={r}>{relLabel(r)}</option>
              ))}
            </select>
            <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label={t("Earlier step")}>
              <option value="">{t("choose an earlier step…")}</option>
              {[...older].reverse().map((e) => (
                <option key={e.id} value={e.id}>#{e.seq} {e.title}</option>
              ))}
            </select>
          </div>
          <textarea placeholder={t("Why? (optional, shown as an author statement)")} value={text}
            onChange={(e) => setText(e.target.value)} rows={2} />
          <button className="primary small" disabled={busy || !target}
            onClick={() =>
              run(
                () => api.createLink({ from: detail.id, to: target, rel, statement: text || undefined }),
                t("Add this link to your real record?"),
                [
                  {
                    label: t("Link"),
                    value: `“${detail.verified.title}” ${relLabel(rel)} “${older.find((e) => e.id === target)?.title ?? ""}”`,
                  },
                  ...(text.trim() ? [{ label: t("Why"), value: text }] : []),
                ],
              )
            }>
            {t("Add relation")}
          </button>
        </div>
      )}
      {mode === "statement" && (
        <div className="group">
          <textarea placeholder={t("Additional note or correction")} value={text} onChange={(e) => setText(e.target.value)} rows={3} />
          {statements.length > 0 && (
            <select value={corrects} onChange={(e) => setCorrects(e.target.value)} aria-label={t("Corrects")}>
              <option value="">{t("(not a correction)")}</option>
              {statements.map((s) => (
                <option key={s.record_id} value={s.record_id}>{t("corrects:")} {s.text?.slice(0, 60)}</option>
              ))}
            </select>
          )}
          <button className="primary small" disabled={busy || !text.trim()}
            onClick={() =>
              run(() => api.createStatement(detail.id, text, corrects || undefined), t("Add this note to your real record?"), [
                { label: t("On"), value: detail.verified.title },
                { label: t("Note"), value: text },
              ])
            }>
            {t("Add statement")}
          </button>
        </div>
      )}
      {mode === "retract" && (
        <div className="group">
          <textarea placeholder={t("Reason for retracting (shown as an author statement)")} value={text}
            onChange={(e) => setText(e.target.value)} rows={2} />
          <button className="primary small" disabled={busy || !text.trim()}
            onClick={() =>
              run(() => api.createRetraction(detail.id, text), t("Retract “{title}”?", { title: detail.verified.title }), [
                { label: t("Reason"), value: text },
              ])
            }>
            {t("Retract this entry")}
          </button>
        </div>
      )}
      {error && !pending && <p className="error small">{error}</p>}
      {pending && (
        <ConfirmRealModal
          title={pending.title}
          items={pending.items}
          confirmLabel={t("Add to my record")}
          busy={busy}
          error={error}
          onConfirm={() => void execute(pending.action)}
          onCancel={() => setPending(null)}
        />
      )}
      <p className="note">{t("Each action is added as a new entry with its own signature and stamps. Nothing already saved is changed.")}</p>
    </section>
  );
}

export function WithdrawRelation({ from, to, rel, onChanged, space, label }: {
  from: string;
  to: string;
  rel: string;
  onChanged: () => void;
  space: Space;
  label: string;
}) {
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function withdraw() {
    setBusy(true);
    setError(null);
    try {
      await api.createLink({ from, to, rel, op: "withdraw" });
      setAsking(false);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="link small" disabled={busy} title={t("Adds a new entry that withdraws this link")}
        onClick={() => (space === "practice" ? void withdraw() : setAsking(true))}>
        {t("withdraw")}
      </button>
      {asking && (
        <ConfirmRealModal
          title={t("Withdraw this link?")}
          items={[{ label: t("Link"), value: label }]}
          confirmLabel={t("Withdraw it")}
          busy={busy}
          error={error}
          onConfirm={() => void withdraw()}
          onCancel={() => setAsking(false)}
        />
      )}
    </>
  );
}
