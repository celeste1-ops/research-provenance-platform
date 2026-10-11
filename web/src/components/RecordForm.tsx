import { useState } from "react";
import { api } from "../api";
import type { GraphNode } from "../types";
import { MarkdownEditor } from "./MarkdownEditor";

const TYPE_LABELS: Record<string, string> = {
  idea: "Idea",
  note: "Note",
  claim: "Claim / hypothesis",
  document: "Document",
  code: "Code",
  experiment: "Experiment",
  dataset: "Dataset",
  figure: "Figure",
  publication: "Publication",
};
const REL_LABELS: Record<string, string> = { revises: "revises", derived_from: "derived from", uses: "uses" };

interface Props {
  projectId: string;
  nodeTypes: string[];
  relationTypes: string[];
  existing: GraphNode[];
  onCreated: (id: string) => void;
  onCancel: () => void;
}

interface Rel {
  to: string;
  rel: string;
}

export function RecordForm({ projectId, nodeTypes, relationTypes, existing, onCreated, onCancel }: Props) {
  const [nodeType, setNodeType] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [repoUrl, setRepoUrl] = useState("");
  const [commit, setCommit] = useState("");
  const [pubKind, setPubKind] = useState<"doi" | "url">("doi");
  const [pubRef, setPubRef] = useState("");
  const [relations, setRelations] = useState<Rel[]>([]);
  const [why, setWhy] = useState("");
  const [milestone, setMilestone] = useState(false);
  const [isImport, setIsImport] = useState(false);
  const [claimedDate, setClaimedDate] = useState("");
  const [level, setLevel] = useState<"L1" | "L2">("L1");
  const [references, setReferences] = useState("");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const codeWithoutArchive = nodeType === "code" && commit.trim() !== "" && files.length === 0;

  function addFiles(list: FileList | null) {
    if (list) setFiles((f) => [...f, ...Array.from(list)]);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const form = new FormData();
    form.set("project_id", projectId);
    form.set("node_type", nodeType);
    form.set("title", title);
    if (body.trim()) form.set("body", body);
    files.forEach((f) => form.append("files", f, f.name));
    if (nodeType === "code" && (repoUrl || commit)) {
      form.set("repo_url", repoUrl);
      form.set("commit", commit);
    }
    if (nodeType === "publication" && pubRef.trim()) form.set(pubKind, pubRef.trim());
    const rels = relations.filter((r) => r.to && r.rel);
    if (rels.length) form.set("relations", JSON.stringify(rels));
    if (why.trim()) form.set("author_statement", why);
    form.set("milestone", milestone ? "true" : "false");
    if (isImport && claimedDate.trim()) {
      form.set("import_claimed_date", claimedDate.trim());
      form.set("import_level", level);
      form.set(
        "import_references",
        JSON.stringify(references.split("\n").map((s) => s.trim()).filter(Boolean)),
      );
    }
    try {
      const out = await api.createEntry(form);
      onCreated(out.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="record-form" onSubmit={submit} data-testid="record-form">
      <h2>New record</h2>
      <fieldset className="types">
        <legend>Type</legend>
        {nodeTypes.map((t) => (
          <label key={t} className={`type-chip ${nodeType === t ? "selected" : ""}`}>
            <input type="radio" name="node_type" value={t} checked={nodeType === t} onChange={() => setNodeType(t)} />
            {TYPE_LABELS[t] ?? t}
          </label>
        ))}
      </fieldset>

      <label>
        Title
        <input name="title" value={title} onChange={(e) => setTitle(e.target.value)} required />
      </label>

      <div className="field">
        <span className="field-label">Body (Markdown)</span>
        <MarkdownEditor value={body} onChange={setBody} />
      </div>

      <div
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
      >
        Drop files here or{" "}
        <label className="link">
          choose files
          <input type="file" multiple hidden onChange={(e) => addFiles(e.target.files)} data-testid="file-input" />
        </label>{" "}
        <span className="muted">(max 50 MB each)</span>
        {files.length > 0 && (
          <ul className="file-list">
            {files.map((f, i) => (
              <li key={i}>
                {f.name} <span className="muted">({f.size} bytes)</span>{" "}
                <button type="button" className="link" onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                  remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {nodeType === "code" && (
        <div className="group">
          <span className="field-label">Code reference</span>
          <div className="row">
            <input placeholder="Repository URL" value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} />
            <input placeholder="Commit hash" value={commit} onChange={(e) => setCommit(e.target.value)} />
          </div>
          <p className="note">
            A commit hash alone is only an external reference: if the repository is deleted or rewritten the code
            cannot be recovered or checked. Attach a <code>git archive</code> file to preserve the code itself. The
            commit date recorded by git is the author's statement, not a verified time.
          </p>
          {codeWithoutArchive && <p className="warning">External reference, code content not saved</p>}
        </div>
      )}

      {nodeType === "publication" && (
        <div className="group">
          <span className="field-label">Publication reference (third-party reference, L2)</span>
          <div className="row">
            <select value={pubKind} onChange={(e) => setPubKind(e.target.value as "doi" | "url")}>
              <option value="doi">DOI</option>
              <option value="url">URL</option>
            </select>
            <input placeholder={pubKind === "doi" ? "10.5281/zenodo…" : "https://…"} value={pubRef}
              onChange={(e) => setPubRef(e.target.value)} />
          </div>
        </div>
      )}

      <div className="group">
        <span className="field-label">Related to earlier records</span>
        {relations.map((r, i) => (
          <div className="row" key={i}>
            <span className="muted">this record</span>
            <select value={r.rel} onChange={(e) => setRelations(relations.map((x, j) => (j === i ? { ...x, rel: e.target.value } : x)))}>
              {relationTypes.map((t) => (
                <option key={t} value={t}>
                  {REL_LABELS[t] ?? t}
                </option>
              ))}
            </select>
            <select value={r.to} onChange={(e) => setRelations(relations.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)))}>
              <option value="">choose a record…</option>
              {[...existing].reverse().map((n) => (
                <option key={n.id} value={n.id}>
                  #{n.seq} {n.title}
                </option>
              ))}
            </select>
            <button type="button" className="link" onClick={() => setRelations(relations.filter((_, j) => j !== i))}>
              remove
            </button>
          </div>
        ))}
        <button type="button" className="secondary small" disabled={existing.length === 0}
          onClick={() => setRelations([...relations, { to: "", rel: relationTypes[0] ?? "revises" }])}>
          + Add relation
        </button>
      </div>

      <label>
        Why? <span className="muted">(optional — shown as an author statement)</span>
        <textarea value={why} onChange={(e) => setWhy(e.target.value)} rows={2} />
      </label>

      <label className="check">
        <input type="checkbox" checked={milestone} onChange={(e) => setMilestone(e.target.checked)} /> Milestone
      </label>

      <label className="check">
        <input type="checkbox" checked={isImport} onChange={(e) => setIsImport(e.target.checked)} /> Importing older
        material
      </label>
      {isImport && (
        <div className="group">
          <p className="note">
            Imported material is only proven to exist from today. The earlier date you enter is shown as an author
            statement; with an external record (DOI, sent e-mail, web archive) mark it L2.
          </p>
          <div className="row">
            <input placeholder="Claimed date: 2025, 2025-11 or 2025-11-03" value={claimedDate}
              onChange={(e) => setClaimedDate(e.target.value)} />
            <select value={level} onChange={(e) => setLevel(e.target.value as "L1" | "L2")}>
              <option value="L1">L1 — author statement only</option>
              <option value="L2">L2 — third-party reference</option>
            </select>
          </div>
          <textarea placeholder="Reference links, one per line" value={references}
            onChange={(e) => setReferences(e.target.value)} rows={2} />
        </div>
      )}

      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
        <button className="primary" disabled={busy || !nodeType || !title.trim()} data-testid="submit-record">
          Record
        </button>
      </div>
      <p className="note center">Once recorded, this cannot be changed — only added to.</p>
    </form>
  );
}
