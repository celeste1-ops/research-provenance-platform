import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Graph as GraphData, Project, Status, TimelineRow } from "./types";
import { BackupDialog } from "./components/BackupDialog";
import { Detail } from "./components/Detail";
import { ExportDialog } from "./components/ExportDialog";
import { Graph } from "./components/Graph";
import { KeyBackupDialog } from "./components/KeyBackupDialog";
import { RecordForm } from "./components/RecordForm";
import { Setup } from "./components/Setup";
import { Timeline } from "./components/Timeline";

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
  const [showBackup, setShowBackup] = useState(false);
  const [version, setVersion] = useState(0);
  const [view, setView] = useState<"graph" | "timeline">("graph");
  const [milestonesOnly, setMilestonesOnly] = useState(false);
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
        <button
          className={status.backup_location ? "secondary" : "secondary attention"}
          onClick={() => setShowBackup(true)}
          title="Full backup: database, files and the encrypted signing key"
        >
          Backup…
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
      <nav className="viewbar">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={view === "graph"} className={view === "graph" ? "tab active" : "tab"}
            onClick={() => setView("graph")}>
            Evolution graph
          </button>
          <button role="tab" aria-selected={view === "timeline"} className={view === "timeline" ? "tab active" : "tab"}
            onClick={() => setView("timeline")} data-testid="tab-timeline">
            Timeline
          </button>
        </div>
        {view === "graph" && (
          <label className="check small">
            <input type="checkbox" checked={milestonesOnly} onChange={(e) => setMilestonesOnly(e.target.checked)}
              data-testid="milestones-only" />
            Milestones only
          </label>
        )}
        <span className="legend small muted">
          solid = revises · dashed = derived from · dotted = uses · T = third-party timestamp · B = Bitcoin anchor
        </span>
      </nav>
      <main className={`main ${selected ? "with-detail" : ""}`}>
        <section className="canvas">
          {view === "timeline" ? (
            <Timeline rows={timeline} onSelect={setSelected} />
          ) : graph ? (
            <Graph data={graph} selected={selected} onSelect={setSelected} milestonesOnly={milestonesOnly} />
          ) : (
            <div className="empty">Loading graph…</div>
          )}
        </section>
        {selected && (
          <Detail
            id={selected}
            version={version}
            onClose={() => setSelected(null)}
            onSelect={setSelected}
            entries={graph?.nodes ?? []}
            relationTypes={status.relation_types}
            onChanged={reload}
            activeRelations={new Set((graph?.edges ?? []).filter((e) => e.active).map((e) => `${e.to}|${e.from}|${e.rel}`))}
          />
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
                if (!status.backup_location) {
                  setMessage(
                    "Recorded. Now set a backup location (“Backup…”): a lost computer or key means lost records or a new identity.",
                  );
                }
              }}
            />
          </div>
        </div>
      )}
      {showBackup && (
        <BackupDialog
          defaultLocation={status.backup_location}
          onClose={() => setShowBackup(false)}
          onDone={(msg) => {
            setShowBackup(false);
            setMessage(msg);
            reload();
          }}
        />
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
