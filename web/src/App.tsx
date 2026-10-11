import { useCallback, useEffect, useRef, useState } from "react";
import { api, setSpace, type Space } from "./api";
import type { Graph as GraphData, Project, Status, TimelineRow } from "./types";
import { BackupDialog, BackupPill } from "./components/BackupDialog";
import { Detail } from "./components/Detail";
import { EmptyState } from "./components/EmptyState";
import { ExportDialog } from "./components/ExportDialog";
import { Graph } from "./components/Graph";
import { Help } from "./components/Help";
import { Legend, TechnicalDetails, WhereIsMyData } from "./components/InfoPanels";
import { KeyBackupDialog } from "./components/KeyBackupDialog";
import { RecordForm } from "./components/RecordForm";
import { ServiceCheckDialog } from "./components/ServiceCheck";
import { Setup } from "./components/Setup";
import { Timeline } from "./components/Timeline";
import { help, homeNote } from "./labels";
import { dev, setDevice } from "./device";
import { lang, setLang, t, tn, tx, type Lang } from "./i18n";
import { LangSwitch } from "./components/LangSwitch";

type Dialog = null | "form" | "export" | "backup" | "key" | "where" | "tech" | "services" | "practice-reset";
const SPACE_KEY = "rprov-space";

// Remembered per browser so a reload stays in the same space (a convenience only).
function initialSpace(): Space {
  let saved: string | null = null;
  try {
    saved = window.localStorage.getItem(SPACE_KEY);
  } catch {
    /* storage unavailable */
  }
  const space: Space = saved === "practice" ? "practice" : "real";
  setSpace(space);
  return space;
}
interface Notice {
  text: string;
  action?: { label: string; onClick: () => void };
  kind?: "info" | "error";
}

export function App() {
  const [space, setSpaceState] = useState<Space>(initialSpace);
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
  const [uiLang, setUiLang] = useState<Lang>(lang);
  const menuRef = useRef<HTMLDivElement>(null);

  const reload = useCallback(async () => {
    try {
      const s = await api.status();
      setDevice(s.device, s.keychain_name);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, space]);

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

  function switchSpace(next: Space) {
    if (next === space) return;
    setSpace(next);
    try {
      window.localStorage.setItem(SPACE_KEY, next);
    } catch {
      /* storage unavailable */
    }
    setMenuOpen(false);
    setDialog(null);
    setSelected(null);
    setGraph(null);
    setTimeline([]);
    setProjects([]);
    setProjectId("");
    setStatus(null);
    setSpaceState(next);
    setNotice(
      next === "real"
        ? { text: t("You are now in My research. Steps you save here are permanent — they can't be changed or deleted.") }
        : null,
    );
  }

  async function resetPractice(sample: boolean) {
    setDialog(null);
    setMenuOpen(false);
    setSelected(null);
    setNotice({ text: sample ? t("Filling practice with the sample research…") : t("Starting practice over…") });
    try {
      await api.practiceReset(sample);
      setProjectId("");
      setGraph(null);
      setNotice({ text: sample ? t("Practice now holds the fictional sample research. Look around freely.") : t("Practice is empty again.") });
      await reload();
    } catch (e) {
      setNotice({ text: (e as Error).message, kind: "error" });
    }
  }

  // Switching language redraws the interface (key below) and asks the server for its texts again.
  function changeLang(next: Lang) {
    setLang(next);
    setUiLang(next);
    api.setPreferences({ language: next }).catch(() => undefined);
    void reload();
  }

  const practice = space === "practice";
  const spaceSwitch = (
    <div className="space-switch" role="group" aria-label={t("Space")}>
      <button aria-pressed={!practice} className={!practice ? "on" : ""} onClick={() => switchSpace("real")}
        data-testid="space-real">
        {t("My research")}
      </button>
      <button aria-pressed={practice} className={practice ? "on" : ""} onClick={() => switchSpace("practice")}
        data-testid="space-practice">
        {t("Practice")}
      </button>
    </div>
  );

  if (!status) return <div className="loading">{t("Loading…")}</div>;
  if (!status.initialized)
    return <Setup key={uiLang} onDone={reload} onPractice={() => switchSpace("practice")} onLang={changeLang} />;

  async function newProject() {
    const title = window.prompt(t("Name of the new research project"));
    if (!title) return;
    const p = await api.createProject(title);
    setProjectId(p.id);
  }

  async function checkProofs() {
    setMenuOpen(false);
    setNotice({ text: t("Checking stamps…") });
    try {
      const stats = await api.refreshAnchors();
      setNotice({
        text: t("Stamps checked: {requested} requested, {done} newly done, {waiting} public stamps still waiting.", {
          requested: stats.submitted,
          done: stats.upgraded,
          waiting: stats.still_pending,
        }),
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
    <div className={`app space-${space}`} key={uiLang}>
      <header className="topbar">
        <div className="brand">{t("Research history")}</div>
        {spaceSwitch}
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label={t("Project")}>
          {projects.length === 0 && <option value="">{t("No project")}</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
        <button className="link small" onClick={newProject}>
          {t("+ New project")}
        </button>
        <span className="muted small" data-testid="step-count">
          {tn(steps, "{n} step", "{n} steps")}
        </span>
        <div className="spacer" />
        {!practice && <BackupPill status={status.backup} onClick={() => setDialog("backup")} />}
        <span className="with-help">
          <button className="secondary" onClick={() => setDialog("export")} disabled={steps === 0}>
            {t("Share")}
          </button>
          <Help id="share" label={t("Share")} align="right">{help("share")}</Help>
        </span>
        <span className="with-help">
          <button className="primary" onClick={() => openForm()} disabled={!projectId} data-testid="new-record">
            {t("+ Add a step")}
          </button>
          <Help id="add-step" label={t("a step")} align="right">{help("addStep")}</Help>
        </span>
        <div className="menu-wrap" ref={menuRef}>
          <button className="secondary" aria-expanded={menuOpen} data-testid="settings-menu"
            onClick={() => setMenuOpen(!menuOpen)}>
            ⚙ {t("Settings")}
          </button>
          {menuOpen && (
            <div className="menu" role="menu">
              <button role="menuitem" onClick={checkProofs}>{t("Check stamps now")}</button>
              <button role="menuitem" onClick={() => openMenuItem("services")}>{t("Check stamp services…")}</button>
              {!practice && <button role="menuitem" onClick={() => openMenuItem("backup")}>{t("Backup…")}</button>}
              <button role="menuitem" onClick={() => openMenuItem("where")}>{t("Where is my data?")}</button>
              <hr />
              <button role="menuitem" onClick={() => openMenuItem("tech")}>{t("Technical details")}</button>
              {!practice && (
                <button role="menuitem" onClick={() => openMenuItem("key")}>{t("Back up signing key only…")}</button>
              )}
              {practice && (
                <>
                  <button role="menuitem" onClick={() => openMenuItem("practice-reset")}>{t("Start practice over…")}</button>
                  <button role="menuitem" onClick={() => resetPractice(true)}>{t("Fill practice with sample research")}</button>
                </>
              )}
            </div>
          )}
        </div>
        <LangSwitch value={uiLang} onChange={changeLang} />
      </header>
      {practice && (
        <div className="practice-banner" data-testid="practice-banner">
          {tx("<b>Practice:</b> nothing here goes into your real record. Try anything.", { b: (s) => <b>{s}</b> })}
          <button className="link small" onClick={() => switchSpace("real")}>
            {t("Back to My research")}
          </button>
        </div>
      )}
      {!practice && status.backup?.other_copy && status.backup.state !== "paused" && (
        <div className="banner error small" data-testid="other-copy-banner">
          <span>
            {t("Another copy of this research (another {device}?) is also backing up into your backup folder. Use only one {device} to add steps.", { device: dev() })}
          </span>
          <button className="secondary small" onClick={() => setDialog("backup")}>
            {t("What to do")}
          </button>
        </div>
      )}
      {status.data_dir_warning && (
        <div className="banner error small" data-testid="data-dir-warning">
          {status.data_dir_warning}
        </div>
      )}
      {btcOff && (
        <div className="banner muted small">{t("Public stamp (Bitcoin): off. Date stamps are on.")}</div>
      )}
      {notice && (
        <div className={`banner ${notice.kind === "error" ? "error" : ""}`} data-testid="notice">
          <span>{notice.text}</span>
          {notice.action && (
            <button className="secondary small" onClick={notice.action.onClick}>
              {notice.action.label}
            </button>
          )}
          <button className="link small dismiss" onClick={() => setNotice(null)} aria-label={t("Dismiss")}>
            ✕
          </button>
        </div>
      )}
      {!empty && (
        <nav className="viewbar">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={view === "graph"} className={view === "graph" ? "tab active" : "tab"}
              onClick={() => setView("graph")}>
              {t("Map")}
            </button>
            <Help id="map" label={t("the map")} wide>
              <Legend />
            </Help>
            <button role="tab" aria-selected={view === "timeline"} className={view === "timeline" ? "tab active" : "tab"}
              onClick={() => setView("timeline")} data-testid="tab-timeline">
              {t("List")}
            </button>
            <Help id="list" label={t("the list")}>{help("list")}</Help>
          </div>
          {view === "graph" && (
            <span className="with-help">
              <label className="check small">
                <input type="checkbox" checked={milestonesOnly} onChange={(e) => setMilestonesOnly(e.target.checked)}
                  data-testid="milestones-only" />
                {t("Key steps only")}
              </label>
              <Help id="key-steps" label={t("Key steps only")}>{help("keySteps")}</Help>
            </span>
          )}
        </nav>
      )}
      <main className={`main ${selected ? "with-detail" : ""}`}>
        <section className="canvas">
          {empty ? (
            <EmptyState
              projectTitle={project?.title ?? t("your research")}
              backup={status.backup}
              onAdd={openForm}
              onBackup={() => setDialog("backup")}
              space={space}
              onSample={() => resetPractice(true)}
            />
          ) : view === "timeline" ? (
            <Timeline rows={timeline} onSelect={setSelected} />
          ) : graph ? (
            <Graph data={graph} selected={selected} onSelect={setSelected} milestonesOnly={milestonesOnly} />
          ) : (
            <div className="empty">{t("Loading…")}</div>
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
            space={space}
          />
        )}
      </main>
      <footer className="footbar small" data-testid="home-note">
        <span>{homeNote()}</span>
        <button className="link small" onClick={() => setDialog("where")}>
          {t("Where is my data?")}
        </button>
      </footer>
      {dialog === "form" && graph && (
        <div className="modal-backdrop">
          <div className="modal">
            <RecordForm
              projectId={projectId}
              nodeTypes={status.node_types}
              relationTypes={status.relation_types}
              existing={graph.nodes}
              initialType={formType}
              space={space}
              onCancel={() => setDialog(null)}
              onCreated={async (id) => {
                setDialog(null);
                setSelected(id);
                await reload();
                const b = (await api.status()).backup;
                if (practice) {
                  setNotice({ text: t("Saved in practice. It is not part of your real record.") });
                } else if (b?.state === "paused") {
                  setNotice({
                    text: t("Saved. Automatic backup is paused since the restore — confirm the folder to resume it."),
                    action: { label: t("Review backup"), onClick: () => setDialog("backup") },
                  });
                } else if (b?.state === "ok") {
                  setNotice({ text: t("Saved. It gets its date stamp in a few seconds and goes into the next automatic backup.") });
                } else {
                  setNotice({
                    text: t("Saved. Automatic backup is not set up yet — if this {device} is lost, this step would be lost too.", { device: dev() }),
                    action: { label: t("Set up backup"), onClick: () => setDialog("backup") },
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
            setNotice({ text: t("Key backup downloaded. Store it and its password separately.") });
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
      {dialog === "services" && <ServiceCheckDialog onClose={() => setDialog(null)} />}
      {dialog === "export" && (
        <ExportDialog rows={timeline} defaultTitle={project?.title ?? t("evidence")} onClose={() => setDialog(null)}
          practice={practice} />
      )}
      {dialog === "practice-reset" && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("Start practice over")}>
          <div className="modal" data-testid="practice-reset">
            <h2>{t("Start practice over?")}</h2>
            <p>
              {t("All practice steps and the practice signing key are thrown away and you get an empty practice space. Your real record is not touched.")}
            </p>
            <div className="actions">
              <button className="secondary" onClick={() => setDialog(null)}>
                {t("Cancel")}
              </button>
              <button className="primary" onClick={() => resetPractice(false)}>
                {t("Start over")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
