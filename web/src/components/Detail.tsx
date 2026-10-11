import { useEffect, useState } from "react";
import { api } from "../api";
import type { RecordDetail } from "../types";
import { Markdown } from "./Markdown";
import { ProofLine } from "./ProofBadge";

interface Props {
  id: string;
  version: number;
  onClose: () => void;
  onSelect: (id: string) => void;
}

// Record detail, split by source with fixed labels: Verified record / Author statement / Later additions.
export function Detail({ id, version, onClose, onSelect }: Props) {
  const [detail, setDetail] = useState<RecordDetail | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setBody(null);
    api
      .record(id)
      .then((d) => {
        if (!live) return;
        setDetail(d);
        if (d.verified.has_body) api.body(id).then((t) => live && setBody(t));
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
        <ProofLine proof={v.timestamps.tsa} />
        <ProofLine proof={v.timestamps.btc} />
        <p className="small">{v.earliest_verified ? v.earliest_verified.text : "No timestamp yet — no time is shown."}</p>
        <dl>
          <dt>Record ID</dt>
          <dd className="mono">{v.record_id}</dd>
          <dt>Signature</dt>
          <dd>{v.signature === "valid" ? "valid (same key as all other records)" : v.signature}</dd>
          {v.project_title && (
            <>
              <dt>Project (as recorded)</dt>
              <dd>{v.project_title}</dd>
            </>
          )}
          {v.external && (
            <>
              <dt>External reference</dt>
              <dd>
                {Object.entries(v.external)
                  .filter(([k]) => !["note", "kind", "evidence_level"].includes(k))
                  .map(([k, val]) => (
                    <div key={k}>
                      {k}: <span className="mono">{val}</span>
                    </div>
                  ))}
                {v.external.evidence_level && <div className="muted small">{v.external.evidence_level}</div>}
                {v.external.note && (
                  <div className={v.external.note.startsWith("External reference") ? "warning" : "muted small"}>
                    {v.external.note}
                  </div>
                )}
              </dd>
            </>
          )}
          {v.content_hashes.map((h) => (
            <div key={h.name} className="hash-row">
              <dt>{h.name}</dt>
              <dd>
                <span className="mono">{h.sha256}</span> · {h.size} bytes
                {h.name !== "body.md" && (
                  <>
                    {" "}·{" "}
                    <a href={`/api/records/${detail.id}/content?file=${encodeURIComponent(h.name)}`}>download</a>
                  </>
                )}
              </dd>
            </div>
          ))}
        </dl>
        {body !== null && (
          <div className="body-view">
            <Markdown text={body} />
          </div>
        )}
        <p className="note">{v.note}</p>
      </section>

      <section className="src src-author" data-source="author" data-testid="section-author">
        <h3 className="src-tag">Author statement</h3>
        <ul>
          {detail.author.items.map((a, i) => (
            <li key={i} data-field={a.field}>
              {a.to ? (
                <button className="link" onClick={() => onSelect(a.to!)}>
                  {a.text}
                </button>
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
    </aside>
  );
}
