import { useEffect, useMemo, type ReactNode } from "react";
import type { Graph, GraphEdge, GraphNode, TimelineRow } from "../types";
import { claimedText, help, referenceHref, typeLabel, typeStyle } from "../labels";
import { t, tn, tx } from "../i18n";
import { contentUrl, previewUrl } from "../api";
import { ProofIcon } from "./ProofBadge";
import { Timeline } from "./Timeline";

// "Steps" (DECISIONS D-054): the first view, the one anybody can read. One card per step, oldest at
// the top, each saying in plain words what it is, when it was stamped and which earlier steps it
// came from. The table of every record (PRD §11's timeline) is one click away.

function relation(rel: string, step: ReactNode): ReactNode {
  const s = { s: () => step };
  switch (rel) {
    case "revises":
      return tx("A new version of <s>step</s>", s);
    case "derived_from":
      return tx("Grew out of <s>step</s>", s);
    case "uses":
      return tx("Builds on <s>step</s>", s);
    default:
      return <>{rel.replace("_", " ")} {step}</>;
  }
}

/** A step's reference outside the app, in a few words: a code commit, a DOI or a link. */
export function referenceText(ext: GraphNode["external"]): string | null {
  if (!ext) return null;
  if (ext.commit) {
    const repo = ext.repo_url ? ` · ${ext.repo_url.replace(/^https?:\/\//, "")}` : "";
    return t("Code commit {commit}", { commit: ext.commit.slice(0, 7) }) + repo;
  }
  if (ext.doi) return `DOI ${ext.doi}`;
  return ext.url ?? null;
}

/** What the step holds — the first lines of its text, its pictures and files, its reference — so it
 * can be read without opening it. The whole of it is in the step's detail. */
function StepContent({ node }: { node: GraphNode }) {
  const files = node.files ?? [];
  const images = files.filter((f) => f.kind === "image").slice(0, 3);
  const ref = referenceText(node.external);
  const href = referenceHref(node.external);
  const claimed = claimedText(node.claimed);
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  if (!node.preview && files.length === 0 && !ref) {
    return (
      <>
        {claimed && <p className="step-claimed small">{claimed}</p>}
        <p className="step-empty muted small">{t("No text — just the title.")}</p>
      </>
    );
  }
  return (
    <div className="step-content">
      {claimed && <p className="step-claimed small">{claimed}</p>}
      {node.preview && <p className="step-preview" data-testid="step-preview">{node.preview}</p>}
      {images.length > 0 && (
        <div className="step-thumbs">
          {images.map((f) => (
            <img key={f.name} src={previewUrl(node.id, f.name)} alt={f.name} title={f.name} loading="lazy" />
          ))}
        </div>
      )}
      {(files.length > 0 || ref) && (
        <div className="step-attach small">
          {files.map((f) => (
            <a key={f.name} className="file-chip" href={contentUrl(node.id, f.name)} onClick={stop}
              title={t("Download {name}", { name: f.name })}>
              📎 {f.name}
            </a>
          ))}
          {ref && (href ? (
            <a className="file-chip ref-chip" href={href} target="_blank" rel="noopener noreferrer" onClick={stop}
              title={t("Opens in your browser. A private page may ask you to sign in, or not open at all.")}>
              🔗 {ref}
            </a>
          ) : <span className="file-chip ref-chip">🔗 {ref}</span>)}
        </div>
      )}
    </div>
  );
}

function cardId(id: string): string {
  return `step-card-${id}`;
}

function show(id: string) {
  document.getElementById(cardId(id))?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function StepRef({ node, onSelect, full }: { node: GraphNode; onSelect: (id: string) => void; full?: boolean }) {
  return (
    <button className="step-ref" title={node.title} style={typeStyle(node.node_type)}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(node.id);
        show(node.id);
      }}>
      #{node.seq}{full && <span className="step-ref-title"> {node.title}</span>}
    </button>
  );
}

function Link({ edge, parent, onSelect }: { edge: GraphEdge; parent: GraphNode; onSelect: (id: string) => void }) {
  return (
    <li className={edge.active ? "" : "withdrawn"}>
      <span className="step-link-arrow" aria-hidden="true">↳</span>
      <span>
        {relation(edge.rel, <StepRef node={parent} onSelect={onSelect} full />)}
        {edge.withdrawn ? (
          <span className="muted"> · {t("withdrawn {date}", { date: edge.withdrawn.time.slice(0, 10) })}</span>
        ) : edge.origin === "link" && edge.added ? (
          <span className="muted"> · {t("added {date}", { date: edge.added.time.slice(0, 10) })}</span>
        ) : null}
      </span>
    </li>
  );
}

function Card({ node, links, next, byId, selected, onSelect }: {
  node: GraphNode;
  links: GraphEdge[];
  next: GraphNode[];
  byId: Map<string, GraphNode>;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const cls = ["step-card", node.milestone ? "milestone" : "", node.retracted ? "retracted" : "", selected ? "selected" : ""];
  return (
    <li className="step-row" id={cardId(node.id)}>
      <div className="step-rail" aria-hidden="true"><span className="step-no" style={typeStyle(node.node_type)}>{node.seq}</span></div>
      <article className={cls.filter(Boolean).join(" ")} style={typeStyle(node.node_type)} onClick={() => onSelect(node.id)}
        data-testid={`step-${node.id}`}>
        <div className="step-top">
          <span className="type-tag">{typeLabel(node.node_type)}</span>
          {node.milestone && <span className="key-tag">★ {t("Key step")}</span>}
          {node.retracted && <span className="retracted-tag">{t("retracted")}</span>}
          <span className="spacer" />
          <span className={node.date.verified ? "step-date" : "step-date unverified"} title={node.date.from}>
            {node.date.time.slice(0, 10)}
            {node.date.verified ? " ✓" : ` (${t("unverified")})`}
          </span>
          <span className="icons">
            <ProofIcon proof={node.tsa} />
            <ProofIcon proof={node.btc} />
          </span>
        </div>
        <button className="step-title" onClick={(e) => { e.stopPropagation(); onSelect(node.id); }}>
          {node.title}
        </button>
        <StepContent node={node} />
        {links.length > 0 && (
          <ul className="step-links">
            {links.map((e) => {
              const parent = byId.get(e.from);
              return parent ? <Link key={e.id} edge={e} parent={parent} onSelect={onSelect} /> : null;
            })}
          </ul>
        )}
        {next.length > 0 && (
          <div className="step-next small">
            <span className="muted">{t("Later steps that build on it:")}</span>{" "}
            {next.map((n) => <StepRef key={n.id} node={n} onSelect={onSelect} />)}
          </div>
        )}
      </article>
    </li>
  );
}

export function Steps({ graph, rows, selected, onSelect, keyOnly, table, onTable }: {
  graph: Graph;
  rows: TimelineRow[];
  selected: string | null;
  onSelect: (id: string) => void;
  keyOnly: boolean;
  table: boolean;
  onTable: (table: boolean) => void;
}) {
  const { sorted, byId, parents, children } = useMemo(() => {
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    const parents = new Map<string, GraphEdge[]>();
    const children = new Map<string, GraphNode[]>();
    for (const e of graph.edges) {
      // An edge runs from the earlier step (e.from) to the later one that names it (e.to).
      parents.set(e.to, [...(parents.get(e.to) ?? []), e]);
      const later = byId.get(e.to);
      if (e.active && later && !(children.get(e.from) ?? []).includes(later)) {
        children.set(e.from, [...(children.get(e.from) ?? []), later]);
      }
    }
    for (const list of children.values()) list.sort((a, b) => a.seq - b.seq);
    return { sorted: [...graph.nodes].sort((a, b) => a.seq - b.seq), byId, parents, children };
  }, [graph]);

  // A step chosen elsewhere (just saved, or a #number in the story) comes into view, also when its
  // card only appears with the next load.
  useEffect(() => {
    if (selected && !table) show(selected);
  }, [selected, table, graph]);

  const shown = keyOnly ? sorted.filter((n) => n.milestone) : sorted;
  const items: ReactNode[] = [];
  let before = 0;
  for (const n of sorted) {
    if (keyOnly && !n.milestone) {
      before += 1;
      continue;
    }
    if (before > 0) {
      items.push(
        <li key={`gap-${n.id}`} className="step-gap muted small">
          {tn(before, "{n} more step in between", "{n} more steps in between")}
        </li>,
      );
      before = 0;
    }
    items.push(
      <Card key={n.id} node={n} links={parents.get(n.id) ?? []} next={children.get(n.id) ?? []} byId={byId}
        selected={n.id === selected} onSelect={onSelect} />,
    );
  }

  return (
    <div className="steps-view" data-testid="steps">
      <div className="steps-head">
        <p className="small muted">
          {keyOnly
            ? t("Key steps only — {n} of {total}.", { n: shown.length, total: sorted.length })
            : t("Oldest at the top, newest at the bottom.")}
        </p>
        <div className="segmented small" role="tablist" aria-label={t("Show as")}>
          <button role="tab" aria-selected={!table} className={table ? "" : "on"} onClick={() => onTable(false)}
            data-testid="steps-cards">
            {t("Cards")}
          </button>
          <button role="tab" aria-selected={table} className={table ? "on" : ""} onClick={() => onTable(true)}
            data-testid="steps-table" title={help("list")}>
            {t("Table")}
          </button>
        </div>
      </div>
      <div className="steps-body">
        {table ? (
          <Timeline rows={rows} onSelect={onSelect} />
        ) : shown.length === 0 ? (
          <div className="empty">{t("No key steps yet. Open a step and mark it as a key step.")}</div>
        ) : (
          <div className="steps-scroll">
            <ol className="step-list">{items}</ol>
          </div>
        )}
      </div>
    </div>
  );
}
