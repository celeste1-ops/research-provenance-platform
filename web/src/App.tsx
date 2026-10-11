import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Graph as GraphData, Project, Status, TimelineRow } from "./types";
import { BackupDialog, BackupPill } from "./components/BackupDialog";
import { Detail } from "./components/Detail";
import { EmptyState } from "./components/EmptyState";
import { ExportDialog } from "./components/ExportDialog";
import { Graph } from "./components/Graph";
import { LegendButton, TechnicalDetails, WhereIsMyData } from "./components/InfoPanels";
import { KeyBackupDialog } from "./components/KeyBackupDialog";
import { RecordForm } from "./components/RecordForm";
import { Setup } from "./components/Setup";
import { Timeline } from "./components/Timeline";

type Dialog = null | "form" | "export" | "backup" | "key" | "where" | "tech";
interface Notice {
  text: string;
  action?: { label: string; onClick: () => void };
  kind?: "info" | "error";
}

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [timeline, setTimeline] = useState<TimelineRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [formType, setFormType] = useState<string | undefined>(undefined);
  const [version, setVersion] = useState(0);
  const [view, setView] = useState<"graph" | "timeline">("graph");
  const [milestonesOnly, setMilestonesOnly] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
      setNotice({ text: (e as Error).message, kind: "error" });
    }
  }, [projectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Keep the backup status fresh (automatic backups run in the background).
  useEffect(() => {
    if (!status?.initialized) return;
    const t = window.setInterval(() => {
      api.status().then(setStatus).catch(() => undefined);
    }, 30000);
    return () => window.clearInterval(t);
  }, [status?.initialized]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  if (!status) return <div className="loading">Loading…</div>;
  if (!status.initialized) return <Setup onDone={reload} />;

  async function newProject() {
    const title = window.prompt("Name of the new research project");
    if (!title) return;
    const p = await api.createProject(title);
    setProjectId(p.id);
  }

  async function checkProofs() {
    setMenuOpen(false);
    setNotice({ text: "Checking timestamps…" });
    try {
      const stats = await api.refreshAnchors();
      setNotice({
        text: `Timestamps checked: ${stats.submitted} requested, ${stats.upgraded} newly confirmed, ${stats.still_pending} still waiting for Bitcoin.`,
      });
      await reload();
    } catch (e) {
      setNotice({ text: (e as Error).message, kind: "error" });
    }
  }

  function openForm(type?: string) {
    setFormType(type);
    setDialog("form");
  }

  function openMenuItem(d: Dialog) {
    setMenuOpen(false);
    setDialog(d);
  }

  const project = projects.find((p) => p.id === projectId);
  const steps = graph?.nodes.length ?? 0;
  const btcOff = status.providers.btc === null;
  const empty = graph !== null && steps === 0;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Research history</div>
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="Project">
          {projects.length === 0 && <option value="">No project</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
        <button className="link small" onClick={newProject}>
          + New project
        </button>
        <span className="muted small" data-testid="step-count">
          {steps} research {steps === 1 ? "step" : "steps"}
        </span>
        <div className="spacer" />
        <BackupPill status={status.backup} onClick={() => setDialog("backup")} />
        <button className="secondary" onClick={() => setDialog("export")} disabled={steps === 0}>
          Share…
        </button>
        <button className="primary" onClick={() => openForm()} disabled={!projectId} data-testid="new-record">
          + Add research step
        </button>
        <div className="menu-wrap" ref={menuRef}>
          <button className="secondary icon" aria-label="More" aria-expanded={menuOpen} data-testid="more-menu"
            onClick={() => setMenuOpen(!menuOpen)}>
            ⋯
          </button>
          {menuOpen && (
            <div className="menu" role="menu">
              <button role="menuitem" onClick={checkProofs}>Check timestamps now</button>
              <button role="menuitem" onClick={() => openMenuItem("backup")}>Backup…</button>
              <button role="menuitem" onClick={() => openMenuItem("where")}>Where is my data?</button>
              <hr />
              <button role="menuitem" onClick={() => openMenuItem("tech")}>Technical details</button>
              <button role="menuitem" onClick={() => openMenuItem("key")}>Back up signing key only…</button>
            </div>
          )}
        </div>
      </header>
      {btcOff && (
        <div className="banner muted small">Bitcoin anchor: not enabled. Third-party timestamps are active.</div>
      )}
      {notice && (
        <div className={`banner ${notice.kind === "error" ? "error" : ""}`} data-testid="notice">
          <span>{notice.text}</span>
          {notice.action && (
            <button className="secondary small" onClick={notice.action.onClick}>
              {notice.action.label}
            </button>
          )}
          <button className="link small dismiss" onClick={() => setNotice(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
      {!empty && (
        <nav className="viewbar">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={view === "graph"} className={view === "graph" ? "tab active" : "tab"}
              onClick={() => setView("graph")}>
              History graph
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
          <LegendButton />
        </nav>
      )}
      <main className={`main ${selected ? "with-detail" : ""}`}>
        <section className="canvas">
          {empty ? (
            <EmptyState
              projectTitle={project?.title ?? "your research"}
              backup={status.backup}
              onAdd={openForm}
              onBackup={() => setDialog("backup")}
            />
          ) : view === "timeline" ? (
            <Timeline rows={timeline} onSelect={setSelected} />
          ) : graph ? (
            <Graph data={graph} selected={selected} onSelect={setSelected} milestonesOnly={milestonesOnly} />
          ) : (
            <div className="empty">Loading…</div>
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
      {dialog === "form" && graph && (
        <div className="modal-backdrop">
          <div className="modal">
            <RecordForm
              projectId={projectId}
              nodeTypes={status.node_types}
              relationTypes={status.relation_types}
              existing={graph.nodes}
              initialType={formType}
              onCancel={() => setDialog(null)}
              onCreated={async (id) => {
                setDialog(null);
                setSelected(id);
                await reload();
                const b = (await api.status()).backup;
                if (b?.state === "ok") {
                  setNotice({ text: "Saved. It is being timestamped and will be included in the next automatic backup." });
                } else {
                  setNotice({
                    text: "Saved. Automatic backup is not set up yet — if this Mac is lost, this step would be lost too.",
                    action: { label: "Set up backup", onClick: () => setDialog("backup") },
                  });
                }
              }}
            />
          </div>
        </div>
      )}
      {dialog === "backup" && (
        <BackupDialog
          status={status.backup}
          onClose={() => setDialog(null)}
          onChanged={(msg) => {
            setDialog(null);
            setNotice({ text: msg });
            reload();
          }}
        />
      )}
      {dialog === "key" && (
        <KeyBackupDialog
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            setNotice({ text: "Key backup downloaded. Store it and its password separately." });
            reload();
          }}
        />
      )}
      {dialog === "where" && (
        <WhereIsMyData status={status} onClose={() => setDialog(null)} onBackup={() => setDialog("backup")} />
      )}
      {dialog === "tech" && (
        <TechnicalDetails status={status} onClose={() => setDialog(null)} onKeyBackup={() => setDialog("key")} />
      )}
      {dialog === "export" && (
        <ExportDialog rows={timeline} defaultTitle={project?.title ?? "evidence"} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}
