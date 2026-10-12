import { useCallback, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  useViewport,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Graph as GraphData, GraphNode } from "../types";
import { claimedText, typeLabel, typeStyle } from "../labels";
import { previewUrl } from "../api";
import { t } from "../i18n";
import { ProofIcon } from "./ProofBadge";
import { referenceText } from "./Steps";

const COL_W = 210;
const ROW_H = 96;
const LEFT = 150;
const TOP = 24;
const NODE_W = 184;
const NODE_H = 74; // about the height of a step's box, for the row names beside it
const LEGEND_KEY = "rprov-map-legend-hidden";

const DASH: Record<string, string | undefined> = { revises: undefined, derived_from: "7 4", uses: "2 4" };

type RecordNodeData = { node: GraphNode; selected: boolean };
type BandNodeData = { width: number };

/** The few words on a line between two steps, shown while the mouse is on one of them. */
function relWords(rel: string): string {
  switch (rel) {
    case "revises":
      return t("new version");
    case "derived_from":
      return t("grew out of");
    case "uses":
      return t("builds on");
    default:
      return rel.replace("_", " ");
  }
}

function RecordNode({ data }: NodeProps<Node<RecordNodeData>>) {
  const n = data.node;
  // One line of what the step holds: its text, else its files, else its reference.
  const glance = n.preview?.split("\n")[0]
    || (n.files?.length ? `📎 ${n.files.map((f) => f.name).join(", ")}` : referenceText(n.external));
  const cls = ["record-node", n.milestone ? "milestone" : "", n.retracted ? "retracted" : "", data.selected ? "selected" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} data-testid={`node-${n.id}`} data-seq={n.seq} style={typeStyle(n.node_type)}>
      <Handle type="target" position={Position.Left} />
      <div className="node-title" title={n.title}>
        {n.milestone && <span className="star">★ </span>}
        {n.title}
      </div>
      {glance && <div className="node-preview" title={n.preview ?? glance}>{glance}</div>}
      <div className="node-meta">
        <span className={n.date.verified ? "" : "unverified"} title={n.date.from}>
          <b className="node-seq">#{n.seq}</b> · {n.date.time.slice(0, 10)}
          {!n.date.verified && ` (${t("unverified")})`}
        </span>
        <span className="icons">
          <ProofIcon proof={n.tsa} />
          <ProofIcon proof={n.btc} />
        </span>
      </div>
      {n.retracted && <div className="retracted-tag">{t("retracted")}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

/** A faint band behind every other row, so the eye can follow a row from its name. */
function Band({ data }: NodeProps<Node<BandNodeData>>) {
  return <div className="lane-band" style={{ width: data.width, height: ROW_H }} />;
}

const nodeTypes = { record: RecordNode, band: Band };

/** The names of the rows stay at the left edge however far the map is moved. */
function RowNames({ rows }: { rows: string[] }) {
  const { y, zoom } = useViewport();
  return (
    <div className="lane-rail" aria-hidden="true">
      {rows.map((row, i) => (
        <div key={row} className="lane-chip" style={{ top: y + (TOP + i * ROW_H + NODE_H / 2) * zoom, ...typeStyle(row) }}>
          {typeLabel(row)}
        </div>
      ))}
    </div>
  );
}

/** What the step under the mouse holds, without opening it: its text, its pictures and files. */
function MapPeek({ node }: { node: GraphNode }) {
  const images = (node.files ?? []).filter((f) => f.kind === "image").slice(0, 2);
  const others = (node.files ?? []).filter((f) => f.kind !== "image");
  const ref = referenceText(node.external);
  const claimed = claimedText(node.claimed);
  return (
    <div className="map-peek" style={typeStyle(node.node_type)} data-testid="map-peek">
      <div className="map-peek-top">
        <span className="type-tag">{typeLabel(node.node_type)}</span>
        <span className="muted small">#{node.seq} · {node.date.time.slice(0, 10)}{node.date.verified ? " ✓" : ""}</span>
      </div>
      <b className="map-peek-title">{node.title}</b>
      {claimed && <div className="step-claimed small">{claimed}</div>}
      {node.preview ? <p className="map-peek-text">{node.preview}</p>
        : !images.length && !others.length && !ref && <p className="muted small">{t("No text — just the title.")}</p>}
      {images.length > 0 && (
        <div className="step-thumbs">{images.map((f) => <img key={f.name} src={previewUrl(node.id, f.name)} alt={f.name} />)}</div>
      )}
      {(others.length > 0 || ref) && (
        <div className="small muted">
          {others.map((f) => `📎 ${f.name}`).join("  ")}{others.length && ref ? "  " : ""}{ref ? `🔗 ${ref}` : ""}
        </div>
      )}
      <div className="small muted map-peek-hint">{t("Click to see all of it")}</div>
    </div>
  );
}

/** How to read the map, in plain words, until the person hides it. */
function MapLegend() {
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem(LEGEND_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggle = (next: boolean) => {
    setHidden(next);
    try {
      window.localStorage.setItem(LEGEND_KEY, next ? "1" : "0");
    } catch {
      /* storage unavailable: for this visit only */
    }
  };
  if (hidden) {
    return (
      <button className="secondary small map-legend-open" onClick={() => toggle(false)} data-testid="map-legend-open">
        {t("How to read the map")}
      </button>
    );
  }
  const line = (dash?: string) => (
    <svg width="34" height="8" aria-hidden="true">
      <line x1="0" y1="4" x2="34" y2="4" stroke="#3b4a63" strokeWidth="2" strokeDasharray={dash} />
    </svg>
  );
  return (
    <div className="map-legend" data-testid="map-legend">
      <div className="map-legend-head">
        <b>{t("How to read the map")}</b>
        <button className="link small" onClick={() => toggle(true)} data-testid="map-legend-hide">{t("Hide")}</button>
      </div>
      <ul>
        <li>{t("Each box is one step: older on the left, newer on the right.")}</li>
        <li>{t("Each row is one kind of step, named on the left.")}</li>
        <li>{t("A line joins two related steps:")}</li>
      </ul>
      <div className="map-legend-lines">
        <span>{line()} {t("new version")}</span>
        <span>{line("7 4")} {t("grew out of")}</span>
        <span>{line("2 4")} {t("builds on")}</span>
      </div>
      <p className="muted">{t("★ gold box: a key step. Point at a step to see only its lines.")}</p>
    </div>
  );
}

interface Props {
  data: GraphData;
  selected: string | null;
  onSelect: (id: string) => void;
  milestonesOnly?: boolean;
}

// The map is redrawn whenever its data is fetched again, often with nothing changed (the app
// loads twice on start-up and after a restore; every save reloads). React Flow measures each
// node before showing it, and a node handed over as a new object is hidden and measured
// again; a second redraw at the wrong moment could leave a node hidden for good. So nodes
// that did not change are handed over as the same object, and changed ones keep their last
// measured size until they are measured again.
function useStableNodes(fresh: Node[]) {
  const previous = useRef(new Map<string, { key: string; node: Node }>());
  const measured = useRef(new Map<string, { width: number; height: number }>());
  const nodes = useMemo(() => {
    const next = new Map<string, { key: string; node: Node }>();
    const out = fresh.map((n) => {
      const key = JSON.stringify([n.type, n.position, n.data, n.selected, n.className]);
      const old = previous.current.get(n.id);
      const size = measured.current.get(n.id);
      const node = old && old.key === key ? old.node : size ? { ...n, measured: size } : n;
      next.set(n.id, { key, node });
      return node;
    });
    previous.current = next;
    return out;
  }, [fresh]);
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    for (const c of changes) {
      if (c.type === "dimensions" && c.dimensions) measured.current.set(c.id, c.dimensions);
    }
  }, []);
  return { nodes, onNodesChange };
}

export function Graph({ data, selected, onSelect, milestonesOnly = false }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);
  const drawn = useMemo(
    () => (milestonesOnly ? milestoneLayout(data, selected) : layout(data, selected)),
    [data, selected, milestonesOnly],
  );
  const { nodes, onNodesChange } = useStableNodes(drawn.nodes);
  const wrap = useRef<HTMLDivElement>(null);
  const peek = hovered ? data.nodes.find((n) => n.id === hovered) ?? null : null;

  // Pointing at a step shows its own lines, named, and fades the rest. The steps themselves are
  // faded with a style rule, so they are never handed to the map again (see useStableNodes).
  const focus = useMemo(() => {
    if (!hovered) return null;
    const ids = new Set([hovered]);
    for (const e of drawn.edges) {
      if (e.source === hovered) ids.add(e.target);
      if (e.target === hovered) ids.add(e.source);
    }
    return ids;
  }, [hovered, drawn.edges]);
  const edges = useMemo(() => {
    if (!focus || !hovered) return drawn.edges;
    return drawn.edges.map((e) => {
      const mine = e.source === hovered || e.target === hovered;
      if (!mine) return { ...e, style: { ...e.style, opacity: 0.12 }, label: undefined };
      const rel = (e.data as { rel?: string } | undefined)?.rel;
      return {
        ...e,
        zIndex: 5,
        label: e.label ?? (rel ? relWords(rel) : undefined),
        style: { ...e.style, stroke: "#2f5bd3", strokeWidth: 2.4 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#2f5bd3" },
      };
    });
  }, [drawn.edges, focus, hovered]);
  const fade = focus
    ? `.graph .react-flow__node-record:not(${[...focus].map((id) => `[data-id="${CSS.escape(id)}"]`).join(",")}) { opacity: .28; }`
    : "";

  // Start where the newest steps are, with every row in sight; the names of the rows stay put.
  const columns = milestonesOnly ? data.milestone_view.nodes.length : data.nodes.length;
  const rowCount = drawn.nodes.filter((n) => n.type === "band").length;
  const onInit = useCallback((flow: ReactFlowInstance) => {
    const box = wrap.current?.getBoundingClientRect();
    if (!box) return;
    const width = LEFT + columns * COL_W + 30;
    const height = TOP + rowCount * ROW_H + 10;
    const zoom = Math.min(1, Math.max(0.6, (box.height - 16) / height));
    const x = width * zoom <= box.width ? (box.width - width * zoom) / 2 : box.width - width * zoom;
    void flow.setViewport({ x, y: 8, zoom });
  }, [columns, rowCount]);

  if (data.nodes.length === 0) {
    return <div className="empty">{t("No records yet. Use “New record” to make the first one.")}</div>;
  }
  if (milestonesOnly && data.milestone_view.nodes.length === 0) {
    return <div className="empty">{t("No milestones yet. Mark important records as milestones.")}</div>;
  }
  return (
    <div className="graph" data-testid="graph" ref={wrap}>
      {fade && <style>{fade}</style>}
      <ReactFlow
        key={milestonesOnly ? "milestones" : "all"} // start again from the newest steps when the mode changes
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onInit={onInit}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          if (node.type === "record") onSelect(node.id);
        }}
        onNodeMouseEnter={(_, node) => node.type === "record" && setHovered(node.id)}
        onNodeMouseLeave={() => setHovered(null)}
      >
        <Background gap={24} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
        <RowNames rows={drawn.rows} />
        <Panel position="top-right">
          <MapLegend />
        </Panel>
        {peek && (
          <Panel position="bottom-left">
            <MapPeek node={peek} />
          </Panel>
        )}
      </ReactFlow>
    </div>
  );
}

// Milestones only (PRD §11): other records fold away; two milestones joined by a relation
// path get one dashed connector labelled with how many records lie in between.
function milestoneLayout(data: GraphData, selected: string | null): Drawn {
  const keep = new Set(data.milestone_view.nodes);
  const kept = data.nodes.filter((n) => keep.has(n.id));
  const rows = data.rows.filter((row) => kept.some((n) => n.node_type === row));
  const base = layout({ ...data, nodes: kept, rows, edges: [] }, selected);
  const edges: Edge[] = data.milestone_view.connectors.map((c, i) => ({
    id: `m${i}`,
    source: c.from,
    target: c.to,
    type: "default",
    label: c.hidden === 0 ? t("directly related") : t("{n} in between", { n: c.hidden }),
    labelStyle: { fontSize: 11, fill: "#1e3a8a" },
    labelBgStyle: { fill: "#ffffff", fillOpacity: 0.9 },
    style: { stroke: "#5b6b8c", strokeWidth: 1.6, strokeDasharray: "6 5" },
    markerEnd: { type: MarkerType.ArrowClosed, color: "#5b6b8c" },
    className: "milestone-connector",
    data: { hidden: c.hidden },
  }));
  return { nodes: base.nodes, edges, rows };
}

type Drawn = { nodes: Node[]; edges: Edge[]; rows: string[] };

function layout(data: GraphData, selected: string | null): Drawn {
  const sorted = [...data.nodes].sort((a, b) => a.seq - b.seq);
  const rowOf = new Map(data.rows.map((t, i) => [t, i]));
  const nodes: Node[] = [];
  const width = LEFT + sorted.length * COL_W + 400;
  data.rows.forEach((row, i) => {
    nodes.push({
      id: `band-${row}`,
      type: "band",
      position: { x: -400, y: TOP + i * ROW_H - (ROW_H - NODE_H) / 2 },
      data: { width },
      className: i % 2 ? "band-odd" : "band-even",
      selectable: false,
      draggable: false,
      focusable: false,
      zIndex: -1,
    });
  });
  sorted.forEach((n, col) => {
    const x = LEFT + col * COL_W;
    nodes.push({
      id: n.id,
      type: "record",
      position: { x, y: TOP + (rowOf.get(n.node_type) ?? 0) * ROW_H },
      data: { node: n, selected: n.id === selected },
      style: { width: NODE_W },
    });
  });
  const edges: Edge[] = data.edges.map((e) => {
    const grey = !e.active;
    const color = grey ? "#b5bac4" : "#3b4a63";
    let label: string | undefined;
    if (e.withdrawn) label = t("withdrawn {date}", { date: e.withdrawn.time.slice(0, 10) });
    else if (e.origin === "link" && e.added) label = t("added {date}", { date: e.added.time.slice(0, 10) });
    return {
      id: e.id,
      source: e.from,
      target: e.to,
      type: "default",
      label,
      labelStyle: { fontSize: 11, fill: "#1e3a8a" },
      labelBgStyle: { fill: "#ffffff", fillOpacity: 0.85 },
      style: { stroke: color, strokeWidth: 1.6, strokeDasharray: DASH[e.rel] ?? (e.rel in DASH ? undefined : "1 3") },
      markerEnd: { type: MarkerType.ArrowClosed, color },
      data: { rel: e.rel },
      ariaLabel: `${e.rel_label}${label ? `, ${label}` : ""}`,
    };
  });
  return { nodes, edges, rows: data.rows };
}
