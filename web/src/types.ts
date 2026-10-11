export type SourceLabel = "verified" | "author" | "ai";

export interface ProofStatus {
  kind: "tsa" | "btc";
  label: string;
  state: "confirmed" | "pending" | "none" | "failed" | "not_enabled";
  text: string;
  time: string | null;
  provider?: string;
  error?: string | null;
}

export interface WhenInfo {
  time: string;
  verified: boolean;
  from: string;
}

export interface GraphNode {
  id: string;
  seq: number;
  title: string;
  node_type: string;
  node_type_label: string;
  project_id: string;
  milestone: boolean;
  retracted: boolean;
  date: WhenInfo;
  tsa: ProofStatus;
  btc: ProofStatus;
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  rel: string;
  rel_label: string;
  origin: "entry" | "link";
  source_label: SourceLabel;
  active: boolean;
  statement: string | null;
  added?: WhenInfo;
  withdrawn?: WhenInfo;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  rows: string[];
  milestone_view: {
    nodes: string[];
    connectors: { from: string; to: string; hidden: number; label: string }[];
  };
}

export interface AuthorItem {
  field: string;
  text: string;
  note: string;
  level?: string;
  references?: string[];
  to?: string;
  rel?: string;
}

export interface LaterItem {
  record_id: string;
  kind: string;
  title: string;
  date: WhenInfo;
  text: string | null;
  source_label: SourceLabel;
}

export interface ContentHash {
  name: string;
  sha256: string;
  size: number;
  media_type: string;
}

export interface RecordDetail {
  id: string;
  seq: number;
  kind: string;
  retracted: boolean;
  revises?: string[];
  verified: {
    label: string;
    source: "verified";
    record_id: string;
    seq: number;
    kind: string;
    title: string;
    node_type?: string;
    node_type_label?: string;
    project_title?: string;
    signature: string;
    timestamps: { tsa: ProofStatus; btc: ProofStatus };
    earliest_verified: { time: string; from: string; text: string } | null;
    content_hashes: ContentHash[];
    has_body?: boolean;
    external?: Record<string, string>;
    public_key?: string;
    note: string;
  };
  author: { label: string; source: "author"; items: AuthorItem[] };
  later: { label: string; items: LaterItem[] };
  files: { role: string; name: string; size: number; media_type: string; sha256: string }[];
}

export interface TimelineRow {
  id: string;
  seq: number;
  kind: string;
  node_type: string | null;
  title: string;
  tsa: ProofStatus;
  btc: ProofStatus;
  earliest_verified: { time: string; from: string; text: string } | null;
  local_time: { value: string; note: string };
  relations: { rel: string; to: string; to_title: string; source_label: SourceLabel }[];
  source_label: SourceLabel;
}

export interface Status {
  initialized: boolean;
  author_label: string | null;
  installation: string | null;
  record_count: number;
  providers: { tsa: string | null; btc: string | null };
  node_types: string[];
  relation_types: string[];
  key_backup_done: boolean;
  backup_location: string | null;
}

export interface Project {
  id: string;
  title: string;
  created_local: string;
}

export interface ExportPreview {
  title: string;
  records: { id: string; seq: number; kind: string; disclosure: string; visible: string[] }[];
  warnings: string[];
  counts: Record<string, number>;
}
