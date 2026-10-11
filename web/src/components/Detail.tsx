import { useEffect, useState } from "react";
import { api } from "../api";
import type { GraphNode, RecordDetail } from "../types";
import { Changes } from "./Changes";
import { LaterActions, WithdrawRelation } from "./LaterActions";
import { Markdown } from "./Markdown";
import { STAMP_NAMES } from "../labels";
import { ProofLine } from "./ProofBadge";

interface Props {
  id: string;
  version: number;
  onClose: () => void;
  onSelect: (id: string) => void;
  entries: GraphNode[];
  relationTypes: string[];
  onChanged: () => void;
  activeRelations: Set<string>;
}

// Record detail, split by source with fixed labels:
// Verified record / Author statement / Later additions / Changes.
export function Detail({ id, version, onClose, onSelect, entries, relationTypes, onChanged, activeRelations }: Props) {
  const [detail, setDetail] = useState<RecordDetail | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    // Clear only when switching records; a refresh of the same record keeps it on screen.
    setDetail((d) => (d && d.id === id ? d : null));
    api
      .record(id)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        if (d.verified.has_body) api.body(id).then((t) => live && setBody(t));
        else setBody(null);
      })
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [id, version]);

  if (error) return <aside className="detail"><p className="error">{error}</p></aside>;
  if (!detail) return <aside className="detail"><p className="muted">Loading…</p></aside>;
  const v = detail.verified;

  return (
    <aside className="detail" data-testid="detail">
      <header>
        <div>
          <div className="muted small">
            #{detail.seq} · {v.node_type_label ?? detail.kind}
            {detail.retracted && <span className="badge retracted"> retracted</span>}
          </div>
          <h2>{v.title}</h2>
        </div>
        <button className="link" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </header>

      <section className="src src-verified" data-source="verified" data-testid="section-verified">
        <h3 className="src-tag">Verified record</h3>
        {body !== null && (
          <div className="body-view">
            <Markdown text={body} />
          </div>
        )}
        {v.external && (
          <div className="external small">
            {Object.entries(v.external)
              .filter(([k]) => !["note", "kind", "evidence_level"].includes(k))
              .map(([k, val]) => (
                <div key={k}>
                  {k === "repo_url" ? "Repository" : k === "commit" ? "Commit" : k.toUpperCase()}:{" "}
                  <span className="mono">{val}</span>
                </div>
              ))}
            {v.external.evidence_level && <div className="muted">{v.external.evidence_level}</div>}
            {v.external.note && (
              <div className={v.external.note.startsWith("External reference") ? "warning" : "muted"}>
                {v.external.note}
              </div>
            )}
          </div>
        )}
        {v.content_hashes.filter((h) => h.name !== "body.md").length > 0 && (
          <ul className="files small">
            {v.content_hashes
              .filter((h) => h.name !== "body.md")
              .map((h) => (
                <li key={h.name}>
                  📎 <a href={`/api/records/${detail.id}/content?file=${encodeURIComponent(h.name)}`}>{h.name}</a>{" "}
                  <span className="muted">({h.size} bytes)</span>
                </li>
              ))}
          </ul>
        )}
        <div className="proofs">
          <ProofLine proof={v.timestamps.tsa} />
          <p className="proof-help small">{proofHelp(v.timestamps.tsa)}</p>
          <ProofLine proof={v.timestamps.btc} />
          <p className="proof-help small">{proofHelp(v.timestamps.btc)}</p>
        </div>
        <p className="small" data-testid="earliest">
          {v.earliest_verified
            ? `Proven to exist by ${v.earliest_verified.time} (from the ${
                v.earliest_verified.from === v.timestamps.tsa.label ? "date stamp" : "public stamp"
              })`
            : "No stamp yet — no time is shown."}
        </p>
        <p className="note">{v.note}</p>
        <details className="tech small">
          <summary>Technical details</summary>
          <dl>
            <dt>Record ID</dt>
            <dd className="mono">{v.record_id}</dd>
            <dt>Stamps, as named in reports</dt>
            <dd>
              {STAMP_NAMES.tsa} = {v.timestamps.tsa.label}
              {v.timestamps.tsa.provider && ` (${v.timestamps.tsa.provider})`} · {STAMP_NAMES.btc} ={" "}
              {v.timestamps.btc.label}
            </dd>
            <dt>Signature</dt>
            <dd>{v.signature === "valid" ? "valid (same key as all other records)" : v.signature}</dd>
            {v.project_title && (
              <>
                <dt>Project (as recorded)</dt>
                <dd>{v.project_title}</dd>
              </>
            )}
            {v.content_hashes.map((h) => (
              <div key={h.name} className="hash-row">
                <dt>{h.name}</dt>
                <dd>
                  <span className="mono">sha256 {h.sha256}</span> · {h.size} bytes
                </dd>
              </div>
            ))}
          </dl>
        </details>
      </section>

      <section className="src src-author" data-source="author" data-testid="section-author">
        <h3 className="src-tag">Author statement</h3>
        <ul>
          {detail.author.items.map((a, i) => (
            <li key={i} data-field={a.field}>
              {a.to ? (
                <>
                  <button className="link" onClick={() => onSelect(a.to!)}>
                    {a.text}
                  </button>
                  {activeRelations.has(`${detail.id}|${a.to}|${a.rel}`) ? (
                    <>
                      {" · "}
                      <WithdrawRelation from={detail.id} to={a.to} rel={a.rel!} onChanged={onChanged} />
                    </>
                  ) : (
                    <span className="muted small"> · withdrawn later</span>
                  )}
                </>
              ) : (
                a.text
              )}
              <div className="muted small">{a.note}</div>
            </li>
          ))}
        </ul>
      </section>

      <section className="src src-later" data-source="later" data-testid="section-later">
        <h3 className="src-tag">Later additions</h3>
        {detail.later.items.length === 0 ? (
          <p className="muted small">None.</p>
        ) : (
          <ul>
            {detail.later.items.map((l) => (
              <li key={l.record_id}>
                <b>{l.title}</b>
                {l.text && <>: {l.text}</>}
                <div className="muted small">
                  added {l.date.time.slice(0, 10)}
                  {!l.date.verified && " (unverified)"} · author statement
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {detail.kind === "entry" && (
        <section className="src src-changes" data-testid="section-changes">
          <h3 className="src-tag">Changes</h3>
          <Changes id={detail.id} revises={detail.revises ?? []}
            titleOf={(rid) => entries.find((e) => e.id === rid)?.title ?? rid.slice(0, 10)} />
        </section>
      )}

      <LaterActions detail={detail} node={entries.find((e) => e.id === detail.id)} entries={entries}
        relationTypes={relationTypes} onChanged={onChanged} />
    </aside>
  );
}

// One plain sentence under each proof status. The two kinds of proof stay separate.
function proofHelp(p: { kind: string; state: string; time: string | null }): string {
  if (p.kind === "tsa") {
    if (p.state === "confirmed") return `An independent timestamp service signed that this step existed at ${p.time}.`;
    if (p.state === "not_enabled") return "Turned off.";
    return "Not received yet — the app keeps trying automatically (e.g. when you are back online).";
  }
  if (p.state === "confirmed") return "Written into the public Bitcoin blockchain — checkable without trusting any company.";
  if (p.state === "pending") return "Waiting for the Bitcoin network; usually confirms within a few hours. Nothing to do.";
  if (p.state === "not_enabled") return "Turned off.";
  return "Not submitted yet — the app keeps trying automatically.";
}
