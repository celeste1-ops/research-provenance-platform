import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Graph as GraphData, Project, Status, TimelineRow } from "./types";
import { Detail } from "./components/Detail";
import { ExportDialog } from "./components/ExportDialog";
import { Graph } from "./components/Graph";
import { KeyBackupDialog } from "./components/KeyBackupDialog";
import { RecordForm } from "./components/RecordForm";
import { Setup } from "./components/Setup";

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [timeline, setTimeline] = useState<TimelineRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [showKeyBackup, setShowKeyBackup] = useState(false);
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      if (!s.initialized) return;
      const ps = await api.projects();
      setProjects(ps);
      const pid = projectId || ps[0]?.id || "";
      if (pid !== projectId) setProjectId(pid);
      const [g, t] = await Promise.all([api.graph(pid || undefined), api.timeline(pid || undefined)]);
      setGraph(g);
      setTimeline(t);
      setVersion((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (!status) return <div className="loading">Loading…</div>;
  if (!status.initialized) return <Setup onDone={reload} />;

  async function newProject() {
    const title = window.prompt("Name of the new research project");
    if (!title) return;
    const p = await api.createProject(title);
    setProjectId(p.id);
  }

  async function refresh() {
    setMessage("Checking time proofs…");
    try {
      const stats = await api.refreshAnchors();
      setMessage(`Time proofs checked: ${stats.submitted} requested, ${stats.upgraded} confirmed, ${stats.still_pending} still pending.`);
      await reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const project = projects.find((p) => p.id === projectId);
  const btcOff = status.providers.btc === null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Research record</div>
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="Project">
          {projects.length === 0 && <option value="">No project</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
        <button className="secondary small" onClick={newProject}>
          + Project
        </button>
        <div className="spacer" />
        <span className="muted small" title="Author label (self-declared)">
          {status.author_label} · {status.record_count} records
        </span>
        <button
          className={status.key_backup_done ? "secondary" : "secondary attention"}
          onClick={() => setShowKeyBackup(true)}
          title="Download a password-protected backup of your signing key"
        >
          Back up key…
        </button>
        <button className="secondary" onClick={refresh} title="Check pending and missing time proofs now">
          Check time proofs
        </button>
        <button className="secondary" onClick={() => setShowExport(true)} disabled={timeline.length === 0}>
          Export…
        </button>
        <button className="primary" onClick={() => setShowForm(true)} disabled={!projectId} data-testid="new-record">
          New record
        </button>
      </header>
      {btcOff && (
        <div className="banner muted small">Bitcoin anchor: not enabled. Third-party timestamps are active.</div>
      )}
      {message && (
        <div className="banner" onClick={() => setMessage(null)}>
          {message}
        </div>
      )}
      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
        </div>
      )}
      <main className={`main ${selected ? "with-detail" : ""}`}>
        <section className="canvas">
          {graph ? (
            <Graph data={graph} selected={selected} onSelect={setSelected} />
          ) : (
            <div className="empty">Loading graph…</div>
          )}
        </section>
        {selected && (
          <Detail id={selected} version={version} onClose={() => setSelected(null)} onSelect={setSelected} />
        )}
      </main>
      {showForm && graph && (
        <div className="modal-backdrop">
          <div className="modal">
            <RecordForm
              projectId={projectId}
              nodeTypes={status.node_types}
              relationTypes={status.relation_types}
              existing={graph.nodes}
              onCancel={() => setShowForm(false)}
              onCreated={async (id) => {
                setShowForm(false);
                setSelected(id);
                await reload();
                if (!status.key_backup_done) {
                  setMessage("Recorded. Now back up your signing key (“Back up key…”): without it, a lost key means a new identity.");
                }
              }}
            />
          </div>
        </div>
      )}
      {showKeyBackup && (
        <KeyBackupDialog
          onClose={() => setShowKeyBackup(false)}
          onDone={() => {
            setShowKeyBackup(false);
            setMessage("Key backup downloaded. Store it and its password separately.");
            reload();
          }}
        />
      )}
      {showExport && (
        <ExportDialog rows={timeline} defaultTitle={project?.title ?? "evidence"} onClose={() => setShowExport(false)} />
      )}
    </div>
  );
}
