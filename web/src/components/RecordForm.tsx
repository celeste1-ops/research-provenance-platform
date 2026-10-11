import { useState } from "react";
import { api, type Space } from "../api";
import type { GraphNode } from "../types";
import { ConfirmReal, type SummaryItem } from "./Confirm";
import { typeLabel } from "../labels";
import { t, tx } from "../i18n";
import { MarkdownEditor } from "./MarkdownEditor";

function relChoice(rel: string): string {
  switch (rel) {
    case "revises":
      return t("is a new version of (revises)");
    case "derived_from":
      return t("grew out of (derived from)");
    case "uses":
      return t("builds on (uses)");
    default:
      return rel;
  }
}

interface Props {
  projectId: string;
  nodeTypes: string[];
  relationTypes: string[];
  existing: GraphNode[];
  onCreated: (id: string) => void;
  onCancel: () => void;
  initialType?: string;
  space: Space;
}

interface Rel {
  to: string;
  rel: string;
}

export function RecordForm({ projectId, nodeTypes, relationTypes, existing, onCreated, onCancel, initialType, space }: Props) {
  const practice = space === "practice";
  const [confirming, setConfirming] = useState(false);
  const [nodeType, setNodeType] = useState(initialType ?? "");
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

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    // The real record is permanent: show exactly what will be saved first. Practice saves directly.
    if (practice) save();
    else setConfirming(true);
  }

  function summary(): SummaryItem[] {
    const items: SummaryItem[] = [
      { label: t("Type"), value: typeLabel(nodeType) },
      { label: t("Title"), value: title },
    ];
    if (body.trim()) items.push({ label: t("Text"), value: body.length > 280 ? `${body.slice(0, 280)}…` : body });
    if (files.length) items.push({ label: t("Files"), value: files.map((f) => f.name).join(", ") });
    if (nodeType === "code" && (repoUrl || commit)) items.push({ label: t("Code reference"), value: `${repoUrl} ${commit}`.trim() });
    if (nodeType === "publication" && pubRef.trim()) items.push({ label: pubKind.toUpperCase(), value: pubRef.trim() });
    const rels = relations.filter((r) => r.to && r.rel);
    if (rels.length)
      items.push({
        label: t("Connected to"),
        value: (
          <ul className="plain">
            {rels.map((r, i) => (
              <li key={i}>
                {relChoice(r.rel)} “{existing.find((n) => n.id === r.to)?.title ?? r.to.slice(0, 10)}”
              </li>
            ))}
          </ul>
        ),
      });
    if (why.trim()) items.push({ label: t("Why"), value: why });
    if (milestone) items.push({ label: t("Key step"), value: t("yes") });
    if (isImport && claimedDate.trim())
      items.push({ label: t("Older material"), value: t("claimed date {date} ({level})", { date: claimedDate.trim(), level }) });
    return items;
  }

  async function save() {
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
    <>
    {confirming && (
      <ConfirmReal
        title={t("Save this step to your real record?")}
        items={summary()}
        busy={busy}
        error={error}
        onConfirm={save}
        onCancel={() => setConfirming(false)}
      />
    )}
    <form className="record-form" onSubmit={submit} data-testid="record-form" hidden={confirming}>
      <h2>{practice ? t("Add a practice step") : t("Add a step")}</h2>
      {practice && <p className="practice-note">{t("Practice: this does not go into your real record.")}</p>}
      <fieldset className="types">
        <legend>{t("What kind of step is it?")}</legend>
        {nodeTypes.map((kind) => (
          <label key={kind} className={`type-chip ${nodeType === kind ? "selected" : ""}`}>
            <input type="radio" name="node_type" value={kind} checked={nodeType === kind} onChange={() => setNodeType(kind)} />
            {typeLabel(kind)}
          </label>
        ))}
      </fieldset>

      <label>
        {t("Title")}
        <input name="title" value={title} onChange={(e) => setTitle(e.target.value)} required
          placeholder={t("e.g. First version of the model")} />
      </label>

      <div className="field">
        <span className="field-label">
          {t("What is it?")} <span className="muted">{t("(text, optional — Markdown works)")}</span>
        </span>
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
        {t("Attach files: drop them here or")}{" "}
        <label className="link">
          {t("choose files")}
          <input type="file" multiple hidden onChange={(e) => addFiles(e.target.files)} data-testid="file-input" />
        </label>{" "}
        <span className="muted">{t("(max 50 MB each)")}</span>
        {files.length > 0 && (
          <ul className="file-list">
            {files.map((f, i) => (
              <li key={i}>
                {f.name} <span className="muted">{t("({n} bytes)", { n: f.size })}</span>{" "}
                <button type="button" className="link" onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                  {t("remove")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {nodeType === "code" && (
        <div className="group">
          <span className="field-label">{t("Code reference")}</span>
          <div className="row">
            <input placeholder={t("Repository URL")} value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} />
            <input placeholder={t("Commit hash")} value={commit} onChange={(e) => setCommit(e.target.value)} />
          </div>
          <p className="note">
            {tx("A commit hash alone is only an external reference: if the repository is deleted or rewritten the code cannot be recovered or checked. Attach a <code>git archive</code> file to preserve the code itself. The commit date recorded by git is the author's statement, not a verified time.", { code: (s) => <code>{s}</code> })}
          </p>
          {codeWithoutArchive && <p className="warning">{t("External reference, code content not saved")}</p>}
        </div>
      )}

      {nodeType === "publication" && (
        <div className="group">
          <span className="field-label">{t("Publication reference (third-party reference, L2)")}</span>
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
        <span className="field-label">{t("How does it connect to earlier steps?")}</span>
        {relations.map((r, i) => (
          <div className="row" key={i}>
            <span className="muted">{t("this step")}</span>
            <select value={r.rel} onChange={(e) => setRelations(relations.map((x, j) => (j === i ? { ...x, rel: e.target.value } : x)))}>
              {relationTypes.map((rel) => (
                <option key={rel} value={rel}>
                  {relChoice(rel)}
                </option>
              ))}
            </select>
            <select value={r.to} onChange={(e) => setRelations(relations.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)))}>
              <option value="">{t("choose an earlier step…")}</option>
              {[...existing].reverse().map((n) => (
                <option key={n.id} value={n.id}>
                  #{n.seq} {n.title}
                </option>
              ))}
            </select>
            <button type="button" className="link" onClick={() => setRelations(relations.filter((_, j) => j !== i))}>
              {t("remove")}
            </button>
          </div>
        ))}
        <button type="button" className="secondary small" disabled={existing.length === 0}
          onClick={() => setRelations([...relations, { to: "", rel: relationTypes[0] ?? "revises" }])}>
          {t("+ Connect to an earlier step")}
        </button>
        {existing.length === 0 && <p className="note">{t("This is the first step — later steps can connect to it.")}</p>}
      </div>

      <label>
        {t("Why?")} <span className="muted">{t("(optional — shown as your own statement, not as a verified fact)")}</span>
        <textarea value={why} onChange={(e) => setWhy(e.target.value)} rows={2} />
      </label>

      <label className="check">
        <input type="checkbox" checked={milestone} onChange={(e) => setMilestone(e.target.checked)} /> {t("Mark as a key step")}{" "}
        <span className="muted">{t("(an important step — shown in “Key steps only”)")}</span>
      </label>

      <label className="check">
        <input type="checkbox" checked={isImport} onChange={(e) => setIsImport(e.target.checked)} />{" "}
        {t("This is older material I'm adding now")}
      </label>
      {isImport && (
        <div className="group">
          <p className="note">
            {t("Imported material is only proven to exist from today. The earlier date you enter is shown as an author statement; with an external record (DOI, sent e-mail, web archive) mark it L2.")}
          </p>
          <div className="row">
            <input placeholder={t("Claimed date: 2025, 2025-11 or 2025-11-03")} value={claimedDate}
              onChange={(e) => setClaimedDate(e.target.value)} />
            <select value={level} onChange={(e) => setLevel(e.target.value as "L1" | "L2")}>
              <option value="L1">{t("L1 — author statement only")}</option>
              <option value="L2">{t("L2 — third-party reference")}</option>
            </select>
          </div>
          <textarea placeholder={t("Reference links, one per line")} value={references}
            onChange={(e) => setReferences(e.target.value)} rows={2} />
        </div>
      )}

      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="button" className="secondary" onClick={onCancel}>
          {t("Cancel")}
        </button>
        <button className="primary" disabled={busy || !nodeType || !title.trim()} data-testid="submit-record">
          {practice ? t("Save practice step") : t("Save step")}
        </button>
      </div>
      <p className="note center">
        {practice
          ? t("Practice steps work like real ones, but they stay in the practice space and can be thrown away.")
          : t("Saved steps can't be edited later — changes are added as new steps or notes, so the history stays honest.")}
      </p>
    </form>
    </>
  );
}
