import { useCallback, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Graph as GraphData, GraphNode } from "../types";
import { TYPE_LABELS } from "../labels";
import { ProofIcon } from "./ProofBadge";

const COL_W = 210;
const ROW_H = 120;
const LEFT = 150;
const TOP = 70;
const NODE_W = 180;

const DASH: Record<string, string | undefined> = { revises: undefined, derived_from: "7 4", uses: "2 4" };

type RecordNodeData = { node: GraphNode; selected: boolean };
type LabelNodeData = { text: string; sub?: string };

function RecordNode({ data }: NodeProps<Node<RecordNodeData>>) {
  const n = data.node;
  const cls = ["record-node", n.milestone ? "milestone" : "", n.retracted ? "retracted" : "", data.selected ? "selected" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} data-testid={`node-${n.id}`} data-seq={n.seq}>
      <Handle type="target" position={Position.Left} />
      <div className="node-title" title={n.title}>
        {n.milestone && <span className="star">★ </span>}
        {n.title}
      </div>
      <div className="node-meta">
        <span className={n.date.verified ? "" : "unverified"} title={n.date.from}>
          {n.date.time.slice(0, 10)}
          {!n.date.verified && " (unverified)"}
        </span>
        <span className="icons">
          <ProofIcon proof={n.tsa} />
          <ProofIcon proof={n.btc} />
        </span>
      </div>
      {n.retracted && <div className="retracted-tag">retracted</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function LaneLabel({ data }: NodeProps<Node<LabelNodeData>>) {
  return <div className="lane-label">{data.text}</div>;
}

function DateLabel({ data }: NodeProps<Node<LabelNodeData>>) {
  return (
    <div className="date-label">
      <div>{data.text}</div>
      {data.sub && <div className="muted small">{data.sub}</div>}
    </div>
  );
}

const nodeTypes = { record: RecordNode, lane: LaneLabel, date: DateLabel };

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
  const drawn = useMemo(
    () => (milestonesOnly ? milestoneLayout(data, selected) : layout(data, selected)),
    [data, selected, milestonesOnly],
  );
  const { nodes, onNodesChange } = useStableNodes(drawn.nodes);
  const edges = drawn.edges;
  if (data.nodes.length === 0) {
    return <div className="empty">No records yet. Use “New record” to make the first one.</div>;
  }
  if (milestonesOnly && data.milestone_view.nodes.length === 0) {
    return <div className="empty">No milestones yet. Mark important records as milestones.</div>;
  }
  return (
    <div className="graph" data-testid="graph">
      <ReactFlow
        key={milestonesOnly ? "milestones" : "all"} // re-fit the view when the mode changes
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        fitView
        fitViewOptions={{ padding: 0.12, maxZoom: 1, minZoom: 0.6 }}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          if (node.type === "record") onSelect(node.id);
        }}
      >
        <Background gap={24} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

// Milestones only (PRD §11): other records fold away; two milestones joined by a relation
// path get one dashed connector labelled with how many records lie in between.
function milestoneLayout(data: GraphData, selected: string | null): { nodes: Node[]; edges: Edge[] } {
  const keep = new Set(data.milestone_view.nodes);
  const kept = data.nodes.filter((n) => keep.has(n.id));
  const rows = data.rows.filter((t) => kept.some((n) => n.node_type === t));
  const base = layout({ ...data, nodes: kept, rows, edges: [] }, selected);
  const edges: Edge[] = data.milestone_view.connectors.map((c, i) => ({
    id: `m${i}`,
    source: c.from,
    target: c.to,
    type: "default",
    label: c.hidden === 0 ? "directly related" : `${c.hidden} in between`,
    labelStyle: { fontSize: 11, fill: "#1e3a8a" },
    labelBgStyle: { fill: "#ffffff", fillOpacity: 0.9 },
    style: { stroke: "#5b6b8c", strokeWidth: 1.6, strokeDasharray: "6 5" },
    markerEnd: { type: MarkerType.ArrowClosed, color: "#5b6b8c" },
    className: "milestone-connector",
    data: { hidden: c.hidden },
  }));
  return { nodes: base.nodes, edges };
}

function layout(data: GraphData, selected: string | null): { nodes: Node[]; edges: Edge[] } {
  const sorted = [...data.nodes].sort((a, b) => a.seq - b.seq);
  const rowOf = new Map(data.rows.map((t, i) => [t, i]));
  const nodes: Node[] = [];
  data.rows.forEach((t, i) => {
    nodes.push({
      id: `lane-${t}`,
      type: "lane",
      position: { x: 0, y: TOP + i * ROW_H + 18 },
      data: { text: TYPE_LABELS[t] ?? `Other: ${t}` },
      selectable: false,
      draggable: false,
    });
  });
  sorted.forEach((n, col) => {
    const x = LEFT + col * COL_W;
    nodes.push({
      id: `date-${n.id}`,
      type: "date",
      position: { x, y: 0 },
      data: { text: n.date.time.slice(0, 10), sub: `#${n.seq}${n.date.verified ? "" : " · unverified"}` },
      selectable: false,
      draggable: false,
    });
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
    if (e.withdrawn) label = `withdrawn ${e.withdrawn.time.slice(0, 10)}`;
    else if (e.origin === "link" && e.added) label = `added ${e.added.time.slice(0, 10)}`;
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
  return { nodes, edges };
}
