export type SourceLabel = "verified" | "author" | "ai";

export interface ProofStatus {
  kind: "tsa" | "btc";
  label: string;
  state: "confirmed" | "pending" | "none" | "failed" | "not_enabled";
  text: string;
  time: string | null;
  provider?: string;
  error?: string | null;
  retrying?: boolean;
}

export interface WhenInfo {
  time: string;
  verified: boolean;
  from: string;
}

export type PreviewKind = "image" | "text" | null; // how the app can show an attached file (D-057)

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
  preview?: string | null; // the first lines of the step's text
  files?: { name: string; kind: PreviewKind }[]; // attached files, and whether the app can show them
  external?: { commit?: string; repo_url?: string; doi?: string; url?: string } | null;
  claimed?: { date: string; precision: string } | null; // an earlier date the author gave (unverified)
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
    external?: Record<string, string> & { saved?: boolean };
    public_key?: string;
    note: string;
  };
  author: { label: string; source: "author"; items: AuthorItem[] };
  later: { label: string; items: LaterItem[] };
  files: { role: string; name: string; size: number; media_type: string; sha256: string; preview?: PreviewKind }[];
  // Date stamps of attached files, taken when they arrived in the inbox (D-049).
  file_stamps?: { file: string; state: string; time: string | null; source: string | null; code: string | null }[];
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

export interface BackupWhere {
  kind: "synced" | "external" | "same-disk" | "missing";
  label: string;
  safe: boolean;
  warning?: string;
}

export interface BackupStatus {
  configured: boolean;
  location: string | null;
  auto: boolean;
  last_backup: string | null;
  last_file: string | null;
  last_error: string | null;
  pending_changes: boolean;
  keep: number;
  where?: BackupWhere;
  needs_password?: boolean;
  state: "off" | "ok" | "same-disk" | "error" | "paused" | "other-copy" | "keychain-denied";
  keychain_denied?: boolean;
  paused_after_restore?: boolean;
  paused_reason?: "restored" | "copied" | null;
  key_fingerprint?: string | null;
  other_copy?: { last_backup: string; copy: string | null } | null;
  recovery?: { configured: boolean; id?: string; created_local?: string };
  data_dir_warning?: string | null;
  recovery_code?: string; // only in the response that created it; never stored
}

export interface LocationCheck {
  ok: boolean;
  kind: string;
  label: string;
  safe: boolean;
  warning?: string;
  creates?: boolean;
}

export interface BackupSuggestion {
  path: string;
  label: string;
  kind: string;
}

export interface Status {
  initialized: boolean;
  inbox?: number;
  author_label: string | null;
  installation: string | null;
  entry_count: number;
  record_count: number;
  backup: BackupStatus | null;
  data_dir: string;
  public_key: string | null;
  providers: { tsa: string | null; btc: string | null };
  node_types: string[];
  relation_types: string[];
  key_backup_done: boolean;
  backup_location: string | null;
  space: "real" | "practice";
  practice_dir: string;
  data_dir_warning: string | null;
  device: string;
  keychain_name: string;
  keychain_denied?: boolean;
  sample?: SampleInfo | null;
}

/** The practice space holds the FSF sample research (DECISIONS D-059). */
export interface SampleInfo {
  version: number;
  lang: string;
  ids: Record<string, string>;
  projects: Record<string, string>;
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

// “Check stamp services” (DECISIONS D-045)
export interface ServiceCheck {
  group: "tsa" | "calendar" | "explorer";
  name: string;
  url: string;
  ok: boolean;
  ms: number | null;
  detail: string;
}

export interface ServiceCheckResult {
  checks: ServiceCheck[];
  in_use: { tsa: string[]; btc: boolean; explorers: boolean };
}

// A git repository whose commits become steps automatically (DECISIONS D-047).
export type GitSource = {
  id: string;
  path: string;
  name: string;
  branch: string;
  project_id: string;
  project_title: string;
  repo_url: string;
  keep_code: boolean;
  added: string;
  last_commit: string | null;
  last_entry: string | null;
  recorded: number;
  checked: string | null;
  error: string | null;
  busy: { done: number; total: number | null } | null;
};

export type GitStatus = { git: boolean; sources: GitSource[] };

export type GitInspect = {
  path: string;
  name: string;
  branches: string[];
  branch: string | null;
  remote_url: string | null;
  commits: number;
  tags: number;
  first_date: string | null;
  last_date: string | null;
  history_steps: number;
  already: boolean;
};

// The research told in sentences from fixed templates (DECISIONS D-048).
export type NarrativeSentence = {
  text: string;
  source: "record" | "author";
  refs: { id: string; seq: number | null }[];
  date: { time: string | null; verified: boolean; from: string } | null;
};
export type Narrative = {
  title: string;
  intro: NarrativeSentence[];
  chapters: { heading: string | null; paragraphs: NarrativeSentence[][] }[];
  steps: number;
};

// Watched folders and the inbox (DECISIONS D-049).
export type WatchedFolder = {
  id: string;
  path: string;
  name: string;
  project_id: string;
  project_title: string;
  added: string;
  checked: string | null;
  error: string | null;
  files: number;
  recorded: number;
};
export type InboxItem = {
  id: string;
  folder_id: string;
  folder: string;
  path: string;
  name: string;
  sha256: string;
  size: number;
  media_type: string;
  node_type: string;
  seen: string;
  stamp: { time: string | null; provider: string } | null;
  stamp_error: string | null;
  previous: string | null;
};
export type InboxStatus = { folders: WatchedFolder[]; items: InboxItem[] };
export type FolderInspect = {
  path: string;
  name: string;
  files: number;
  too_large: number;
  too_many: boolean;
  max_files: number;
  max_existing: number;
  already: boolean;
};

// A retelling by a language model on this computer, labelled "AI inference" (DECISIONS D-050).
export type AiBlock =
  | { kind: "heading"; text: string }
  | { kind: "break" }
  | { kind: "item" } // a bullet point begins; its sentences follow
  | { kind: "sentence"; text: string; status: "ok" | "no_source" | "unknown_source" | "claim";
      refs: { seq: number; id: string | null }[] };
export type AiResult = {
  label: string;
  model: string;
  url: string;
  created: string;
  title: string;
  facts: number;
  blocks: AiBlock[];
  counts: { ok: number; flagged: number };
};
