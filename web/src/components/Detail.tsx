import { useEffect, useState } from "react";
import { api, contentUrl, previewText, previewUrl, type Space } from "../api";
import type { GraphNode, PreviewKind, RecordDetail } from "../types";
import { Changes } from "./Changes";
import { LaterActions, WithdrawRelation } from "./LaterActions";
import { Markdown } from "./Markdown";
import { referenceHref, stampName } from "../labels";
import { t, tx } from "../i18n";
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
  space: Space;
}

// Record detail, split by source with fixed labels:
// Verified record / Author statement / Later additions / Changes.
/** An attached file shown in place when the app can show it safely (D-057): a picture, or the
 * start of a text file; anything else opens with the program it belongs to. */
function FilePreview({ id, name, kind }: { id: string; name: string; kind: PreviewKind }) {
  const [text, setText] = useState<{ text: string; truncated: boolean } | null>(null);
  const [open, setOpen] = useState(false);
  if (kind === "image") {
    return (
      <a className="file-image" href={previewUrl(id, name)} target="_blank" rel="noopener noreferrer"
        title={t("Open the picture on its own")}>
        <img src={previewUrl(id, name)} alt={name} loading="lazy" data-testid="file-image" />
      </a>
    );
  }
  if (kind === "text") {
    return (
      <>
        {" "}
        <button className="link small" data-testid="file-preview-toggle" onClick={() => {
          setOpen(!open);
          if (!text) previewText(id, name).then(setText).catch(() => setText({ text: t("Could not show this file."), truncated: false }));
        }}>
          {open ? t("Hide") : t("Show what it says")}
        </button>
        {open && (
          <pre className="file-text" data-testid="file-text">
            {text ? text.text : t("Loading…")}
            {text?.truncated && <span className="muted">{"\n"}{t("… only the start is shown; download the file for all of it.")}</span>}
          </pre>
        )}
      </>
    );
  }
  return <span className="muted"> · {t("open it with the program it belongs to")}</span>;
}

export function Detail({ id, version, onClose, onSelect, entries, relationTypes, onChanged, activeRelations, space }: Props) {
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
        if (d.verified.has_body) api.body(id).then((text) => live && setBody(text));
        else setBody(null);
      })
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [id, version]);

  if (error) return <aside className="detail"><p className="error">{error}</p></aside>;
  if (!detail) return <aside className="detail"><p className="muted">{t("Loading…")}</p></aside>;
  const v = detail.verified;

  return (
    <aside className="detail" data-testid="detail">
      <header>
        <div>
          <div className="muted small">
            #{detail.seq} · {v.node_type_label ?? detail.kind}
            {detail.retracted && <span className="badge retracted"> {t("retracted")}</span>}
          </div>
          <h2>{v.title}</h2>
        </div>
        <button className="link" onClick={onClose} aria-label={t("Close")}>
          ✕
        </button>
      </header>

      <section className="src src-verified" data-source="verified" data-testid="section-verified">
        <h3 className="src-tag">{t("Verified record")}</h3>
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
                  {k === "repo_url" ? t("Repository") : k === "commit" ? t("Commit") : k.toUpperCase()}:{" "}
                  {(k === "repo_url" || k === "doi" || k === "url") && referenceHref({ [k]: String(val) }) ? (
                    <a className="mono" href={referenceHref({ [k]: String(val) }) ?? undefined} target="_blank"
                      rel="noopener noreferrer"
                      title={t("Opens in your browser. A private page may ask you to sign in, or not open at all.")}>
                      {String(val)}
                    </a>
                  ) : <span className="mono">{val}</span>}
                </div>
              ))}
            {v.external.evidence_level && <div className="muted">{v.external.evidence_level}</div>}
            {v.external.note && (
              <div className={v.external.saved === false ? "warning" : "muted"}>
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
                  📎 <a href={contentUrl(detail.id, h.name)}>{h.name}</a>{" "}
                  <span className="muted">{t("({n} bytes)", { n: h.size })}</span>
                  <FilePreview id={detail.id} name={h.name}
                    kind={detail.files.find((f) => f.role === "file" && f.name === h.name)?.preview ?? null} />
                </li>
              ))}
          </ul>
        )}
        {(detail.file_stamps ?? []).map((f) => (
          <p key={f.file} className={`small ${f.state === "verified" ? "" : "warning"}`} data-testid="file-stamp">
            {f.state === "verified"
              ? t("Date stamp ✓ of the file {file}: it existed by {time}, when it arrived in the inbox.", { file: f.file, time: f.time ?? "" })
              : t("Date stamp of the file {file}: could not be verified ({code}).", { file: f.file, code: f.code ?? f.state })}
          </p>
        ))}
        <div className="proofs">
          <ProofLine proof={v.timestamps.tsa} />
          <p className="proof-help small">{proofHelp(v.timestamps.tsa)}</p>
          <ProofLine proof={v.timestamps.btc} />
          <p className="proof-help small">{proofHelp(v.timestamps.btc)}</p>
        </div>
        <p className="small" data-testid="earliest">
          {v.earliest_verified
            ? v.earliest_verified.from === v.timestamps.tsa.label
              ? t("Proven to exist by {time} (from the date stamp)", { time: v.earliest_verified.time })
              : t("Proven to exist by {time} (from the public stamp)", { time: v.earliest_verified.time })
            : t("No stamp yet — no time is shown.")}
        </p>
        <p className="note">{v.note}</p>
        <details className="tech small">
          <summary>{t("Technical details")}</summary>
          <dl>
            <dt>{t("Record ID")}</dt>
            <dd className="mono">{v.record_id}</dd>
            <dt>{t("Stamps, as named in reports")}</dt>
            <dd>
              {stampName("tsa")} = {v.timestamps.tsa.label}
              {v.timestamps.tsa.provider && ` (${v.timestamps.tsa.provider})`} · {stampName("btc")} ={" "}
              {v.timestamps.btc.label}
            </dd>
            <dt>{t("Signature")}</dt>
            <dd>{v.signature === "valid" ? t("valid (same key as all other records)") : v.signature}</dd>
            {v.project_title && (
              <>
                <dt>{t("Project (as recorded)")}</dt>
                <dd>{v.project_title}</dd>
              </>
            )}
            {v.content_hashes.map((h) => (
              <div key={h.name} className="hash-row">
                <dt>{h.name}</dt>
                <dd>
                  <span className="mono">sha256 {h.sha256}</span> · {t("{n} bytes", { n: h.size })}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      </section>

      <section className="src src-author" data-source="author" data-testid="section-author">
        <h3 className="src-tag">{t("Author statement")}</h3>
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
                      <WithdrawRelation from={detail.id} to={a.to} rel={a.rel!} onChanged={onChanged} space={space}
                        label={a.text} />
                    </>
                  ) : (
                    <span className="muted small"> · {t("withdrawn later")}</span>
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
        <h3 className="src-tag">{t("Later additions")}</h3>
        {detail.later.items.length === 0 ? (
          <p className="muted small">{t("None.")}</p>
        ) : (
          <ul>
            {detail.later.items.map((l) => (
              <li key={l.record_id}>
                {l.text ? tx("<b>{title}</b>: {text}", { b: (x) => <b>{x}</b> }, { title: l.title, text: l.text }) : <b>{l.title}</b>}
                <div className="muted small">
                  {t("added {date}", { date: l.date.time.slice(0, 10) })}
                  {!l.date.verified && ` (${t("unverified")})`} · {t("author statement")}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {detail.kind === "entry" && (
        <section className="src src-changes" data-testid="section-changes">
          <h3 className="src-tag">{t("Changes")}</h3>
          <Changes id={detail.id} revises={detail.revises ?? []}
            titleOf={(rid) => entries.find((e) => e.id === rid)?.title ?? rid.slice(0, 10)} />
        </section>
      )}

      <LaterActions detail={detail} node={entries.find((e) => e.id === detail.id)} entries={entries}
        relationTypes={relationTypes} onChanged={onChanged} space={space} />
    </aside>
  );
}

// One plain sentence under each proof status. The two kinds of proof stay separate.
function proofHelp(p: { kind: string; state: string; time: string | null }): string {
  if (p.kind === "tsa") {
    if (p.state === "confirmed") return t("An independent timestamp service signed that this step existed at {time}.", { time: p.time ?? "" });
    if (p.state === "not_enabled") return t("Turned off.");
    return t("Not received yet — the app keeps trying automatically (e.g. when you are back online).");
  }
  if (p.state === "confirmed") return t("Written into the public Bitcoin blockchain — checkable without trusting any company.");
  if (p.state === "pending") return t("Waiting for the Bitcoin network; usually confirms within a few hours. Nothing to do.");
  if (p.state === "not_enabled") return t("Turned off.");
  return t("Not submitted yet — the app keeps trying automatically.");
}
