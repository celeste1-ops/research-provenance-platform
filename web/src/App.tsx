import { useCallback, useEffect, useRef, useState } from "react";
import { api, KEYCHAIN_DENIED_EVENT, setSpace, type Space } from "./api";
import type { Graph as GraphData, Project, Status, TimelineRow } from "./types";
import { BackupDialog, BackupPill } from "./components/BackupDialog";
import { Detail } from "./components/Detail";
import { EmptyState } from "./components/EmptyState";
import { ExportDialog } from "./components/ExportDialog";
import { Graph } from "./components/Graph";
import { Help } from "./components/Help";
import { Legend, TechnicalDetails, WhereIsMyData } from "./components/InfoPanels";
import { KeyBackupDialog } from "./components/KeyBackupDialog";
import { GitDialog } from "./components/GitDialog";
import { ImportDialog } from "./components/ImportDialog";
import { FolderDialog, InboxDialog } from "./components/InboxDialogs";
import { NewProject } from "./components/NewProject";
import { QuickNote } from "./components/QuickNote";
import { RecordForm } from "./components/RecordForm";
import { ServiceCheckDialog } from "./components/ServiceCheck";
import { Setup } from "./components/Setup";
import { SampleTour, type TourAction } from "./components/SampleTour";
import { Steps } from "./components/Steps";
import { Story } from "./components/Story";
import { help, homeNote } from "./labels";
import { dev, keychainName, setDevice } from "./device";
import { chosenHere, lang, setLang, t, tn, tx, type Lang } from "./i18n";
import { LangSwitch } from "./components/LangSwitch";
import { GearIcon, ListIcon, LogoMark, MapIcon, NoteIcon, PlusIcon, ShareIcon, StoryIcon } from "./components/Icons";

type Dialog = null | "form" | "export" | "backup" | "key" | "where" | "tech" | "services" | "practice-reset" | "new-project" | "git"
  | "quick" | "folders" | "inbox" | "import" | "example-confirm";
const QUICK_NOTE_HASH = "#quick-note"; // the menu bar / tray icon opens the page with it (D-047)
const SPACE_KEY = "rprov-space";
const TIPS_KEY = "rprov-tips-hidden"; // the person clicked "Got it" on the how-to line
const VIEW_KEY = "rprov-view"; // the view chosen last time
type View = "steps" | "graph" | "story";

function initialView(): View {
  try {
    const saved = window.localStorage.getItem(VIEW_KEY);
    if (saved === "graph" || saved === "story") return saved;
  } catch {
    /* storage unavailable */
  }
  return "steps";
}
const NEW_PROJECT = "__new_project__"; // the last entry of the project list

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
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [tipsHidden, setTipsHidden] = useState(() => {
    try {
      return window.localStorage.getItem(TIPS_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [fileOver, setFileOver] = useState(false);
  const [version, setVersion] = useState(0);
  const [view, setViewState] = useState<View>(initialView);
  const [stepsTable, setStepsTable] = useState(false);
  const [milestonesOnly, setMilestonesOnly] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [tourStart, setTourStart] = useState(0); // "See the example" asked for the tour (D-062)
  const [menuOpen, setMenuOpen] = useState(false);
  const [uiLang, setUiLang] = useState<Lang>(lang);
  const menuRef = useRef<HTMLDivElement>(null);

  // Set when reload() itself picks the project, so that this choice does not load everything again.
  const pickedByReload = useRef(false);
  // Only the newest load may change the page: an older one that answers late (say, for the practice
  // project a reset has just replaced) is dropped instead of emptying the map.
  const loads = useRef(0);

  const reload = useCallback(async () => {
    const load = ++loads.current;
    const stale = () => load !== loads.current;
    try {
      const s = await api.status();
      if (stale()) return;
      setDevice(s.device, s.keychain_name);
      setStatus(s);
      if (!s.initialized) return;
      const ps = await api.projects();
      if (stale()) return;
      setProjects(ps);
      const pid = projectId || ps[0]?.id || "";
      if (pid !== projectId) {
        pickedByReload.current = true;
        setProjectId(pid);
      }
      // The map first; the list's data is asked for after it, so it never holds the map up.
      const g = await api.graph(pid || undefined);
      if (stale()) return;
      setGraph(g);
      setVersion((v) => v + 1);
      const rows = await api.timeline(pid || undefined);
      if (stale()) return;
      setTimeline(rows);
    } catch (e) {
      if (!stale()) setNotice({ text: (e as Error).message, kind: "error" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, space]);

  useEffect(() => {
    if (pickedByReload.current) {
      pickedByReload.current = false;
      return;
    }
    reload();
  }, [reload]);

  // An answer said the keychain refused access: show the banner now, not at the next refresh.
  useEffect(() => {
    const refresh = () => api.status().then(setStatus).catch(() => undefined);
    window.addEventListener(KEYCHAIN_DENIED_EVENT, refresh);
    return () => window.removeEventListener(KEYCHAIN_DENIED_EVENT, refresh);
  }, []);

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

  function switchSpace(next: Space, clearNotice = true) {
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
    setMilestonesOnly(false);
    if (next === "real") {
      setNotice({ text: t("You are now in My research. Steps you save here are permanent — they can't be changed or deleted.") });
    } else if (clearNotice) {
      setNotice(null);
    }
  }

  async function resetPractice(sample: boolean) {
    setDialog(null);
    setMenuOpen(false);
    setSelected(null);
    setNotice({ text: sample ? t("Filling practice with the sample research…") : t("Starting practice over…") });
    try {
      await api.practiceReset(sample, lang());
      setNotice({ text: sample ? t("Practice now holds the fictional sample research. Look around freely.") : t("Practice is empty again.") });
      if (space !== "practice") {
        switchSpace("practice", false);  // from the first screen or the real record
        return;
      }
      setProjectId("");
      setGraph(null);
      setMilestonesOnly(false);
      await reload();
    } catch (e) {
      setNotice({ text: (e as Error).message, kind: "error" });
    }
  }

  // "See the example" (D-062), from either space: the sample in practice, with its tour from the
  // first stop. Only the practice space is ever changed — and a practice space holding steps of the
  // author's own is replaced only after they say so.
  async function seeExample() {
    setMenuOpen(false);
    setDialog(null);
    try {
      const state = await api.practiceState();
      if (!state.sample && state.own_steps > 0) {
        setDialog("example-confirm");
        return;
      }
      await openExample(state.sample);
    } catch (e) {
      setNotice({ text: (e as Error).message, kind: "error" });
    }
  }

  async function openExample(alreadyThere: boolean) {
    setDialog(null);
    setTourStart((n) => n + 1);
    if (!alreadyThere) {
      await resetPractice(true);
    } else if (space !== "practice") {
      switchSpace("practice", false);
    }
  }

  // A stop of the sample tour (D-059): open the part of the app it is about.
  function tourStop(action: TourAction) {
    setDialog(null);
    if ("export" in action) {
      setDialog("export");
      return;
    }
    const main = status?.sample?.projects.main;
    if ("project" in action) {
      setSelected(null);
      setMilestonesOnly(false);
      setView("steps");
      setProjectId(action.project);
      return;
    }
    if (main && projectId !== main) setProjectId(main);
    if ("keyOnly" in action) {
      setSelected(null);
      setView("steps");
      setStepsTable(false);
      setMilestonesOnly(true);
      return;
    }
    setMilestonesOnly(false);
    if ("view" in action) {
      setSelected(null);
      setView(action.view);
      if (action.view === "steps") setStepsTable(false);
      return;
    }
    setView("steps");
    setStepsTable(false);
    setSelected(action.select);
  }

  // The keychain refused access, so the app stopped asking (a refusal is never retried on its own).
  // Trying again makes the system ask now, while the person is looking.
  async function retryKeychain() {
    try {
      const out = await api.keychainRetry();
      if (out.keychain_denied) {
        setNotice({ text: t("The {keychain} still refuses access. When the system asks, choose “Always Allow” and enter your login password.", { keychain: keychainName() }), kind: "error" });
      } else {
        setNotice({ text: t("The {keychain} gave access again. Backups and saving work as before.", { keychain: keychainName() }) });
      }
    } catch (e) {
      setNotice({ text: (e as Error).message, kind: "error" });
    }
    await reload();
  }

  // Switching language redraws the interface (key below) and asks the server for its texts again.
  function changeLang(next: Lang) {
    setLang(next);
    setUiLang(next);
    api.setPreferences({ language: next }).catch(() => undefined);
    void reload();
  }

  // The language is shared with the menu bar / tray menu (D-046): a choice made in another browser
  // wins over this browser's guess, and a first guess is remembered for the menu.
  useEffect(() => {
    api.preferences()
      .then((p) => {
        if (!p.language) api.setPreferences({ language: lang() }).catch(() => undefined);
        else if (p.language !== lang() && !chosenHere()) changeLang(p.language);
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // "Quick note…" in the menu bar / tray menu opens the page at #quick-note.
  useEffect(() => {
    const open = () => {
      if (window.location.hash !== QUICK_NOTE_HASH) return;
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      setDialog("quick");
    };
    open();
    window.addEventListener("hashchange", open);
    return () => window.removeEventListener("hashchange", open);
  }, []);

  // Files dragged from Finder / Explorer: dropped anywhere on the page they open "Add a step" with
  // the files attached (the form itself takes drops too). A browser would otherwise open the file
  // in place of the app.
  const canDropHere = Boolean(status?.initialized) && dialog === null && graph !== null;
  useEffect(() => {
    const hasFiles = (e: DragEvent) => Boolean(e.dataTransfer?.types.includes("Files"));
    const over = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = canDropHere ? "copy" : "none";
      setFileOver(canDropHere);
    };
    const leave = (e: DragEvent) => {
      if (e.relatedTarget === null) setFileOver(false);  // left the window
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setFileOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (canDropHere && files.length) openForm(undefined, files);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canDropHere]);

  if (!status) return <div className="loading">{t("Loading…")}</div>;
  if (!status.initialized)
    return <Setup key={uiLang} onDone={reload} onPractice={() => switchSpace("practice")}
      onSample={() => void resetPractice(true)} onLang={changeLang} />;

  function projectCreated(id: string) {
    setDialog(null);
    setProjectId(id);  // a new project id reloads the list of projects too
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

  function setView(next: View) {
    setViewState(next);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      /* storage unavailable: remembered for this visit */
    }
  }

  function hideTips() {
    setTipsHidden(true);
    try {
      window.localStorage.setItem(TIPS_KEY, "1");
    } catch {
      /* storage unavailable: hidden for this visit */
    }
  }

  function openForm(type?: string, files: File[] = []) {
    setFormType(type);
    setDroppedFiles(files);
    setDialog("form");
  }


  async function afterSaved(id: string) {
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
    } else if (b?.state === "same-disk" && b.where?.kind === "same-disk") {
      setNotice({
        text: t("Saved. It goes into the next automatic backup — but the backup folder is on this {device} only, so it won't help if the {device} is lost.", { device: dev() }),
        action: { label: t("Review backup"), onClick: () => setDialog("backup") },
      });
    } else if (b?.configured) {
      setNotice({
        text: t("Saved. Automatic backup needs a look — open Backup to see why."),
        action: { label: t("Review backup"), onClick: () => setDialog("backup") },
      });
    } else {
      setNotice({
        text: t("Saved. Automatic backup is not set up yet — if this {device} is lost, this step would be lost too.", { device: dev() }),
        action: { label: t("Set up backup"), onClick: () => setDialog("backup") },
      });
    }
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
      {/* Row 1 — where am I: the app, the space, the project, its state, settings. */}
      <header className="appbar">
        <div className="brand"><LogoMark /> {t("Research history")}</div>
        {spaceSwitch}
        <div className="project-picker">
          <select value={projectId} aria-label={t("Project")} data-testid="project-select"
            onChange={(e) => (e.target.value === NEW_PROJECT ? setDialog("new-project") : setProjectId(e.target.value))}>
            {projects.length === 0 && <option value="">{t("No project")}</option>}
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
            <option value={NEW_PROJECT}>{t("+ New project…")}</option>
          </select>
          <span className="muted small" data-testid="step-count">
            {tn(steps, "{n} step", "{n} steps")}
          </span>
        </div>
        <div className="spacer" />
        {(status.inbox ?? 0) > 0 && (
          <button className="pill pill-inbox" onClick={() => setDialog("inbox")} data-testid="inbox-pill">
            {t("Inbox ({n})", { n: status.inbox ?? 0 })}
          </button>
        )}
        {!practice && <BackupPill status={status.backup} onClick={() => setDialog("backup")} />}
        <div className="menu-wrap" ref={menuRef}>
          <button className="ghost" aria-expanded={menuOpen} data-testid="settings-menu"
            onClick={() => setMenuOpen(!menuOpen)}>
            <GearIcon /> {t("Settings")}
          </button>
          {menuOpen && (
            <div className="menu" role="menu">
              <div className="menu-section" role="presentation">{t("Record automatically")}</div>
              <button role="menuitem" onClick={() => openMenuItem("git")} data-testid="menu-git">
                {t("Record from git…")}
              </button>
              <button role="menuitem" onClick={() => openMenuItem("folders")} data-testid="menu-folders">
                {t("Watch a folder…")}
              </button>
              <div className="menu-section" role="presentation">{t("Earlier material")}</div>
              <button role="menuitem" onClick={() => openMenuItem("import")} data-testid="menu-import">
                {t("Import notes or a table…")}
              </button>
              <div className="menu-section" role="presentation">{t("Stamps")}</div>
              <button role="menuitem" onClick={checkProofs}>{t("Check stamps now")}</button>
              <button role="menuitem" onClick={() => openMenuItem("services")}>{t("Check stamp services…")}</button>
              <div className="menu-section" role="presentation">{t("Your data")}</div>
              {!practice && <button role="menuitem" onClick={() => openMenuItem("backup")}>{t("Backup…")}</button>}
              {!practice && (
                <button role="menuitem" onClick={() => openMenuItem("key")}>{t("Back up signing key only…")}</button>
              )}
              <button role="menuitem" onClick={() => openMenuItem("where")}>{t("Where is my data?")}</button>
              {practice && (
                <>
                  <div className="menu-section" role="presentation">{t("Practice")}</div>
                  <button role="menuitem" onClick={() => openMenuItem("practice-reset")}>{t("Start practice over…")}</button>
                  <button role="menuitem" onClick={() => resetPractice(true)}>{t("Fill practice with sample research")}</button>
                </>
              )}
              <div className="menu-section" role="presentation">{t("About")}</div>
              <button role="menuitem" onClick={() => void seeExample()} data-testid="menu-example">{t("See the example")}</button>
              <button role="menuitem" onClick={() => openMenuItem("tech")}>{t("Technical details")}</button>
            </div>
          )}
        </div>
        <LangSwitch value={uiLang} onChange={changeLang} />
      </header>
      {/* Row 2 — what can I do: look at the research three ways, or add to it and share it. */}
      <nav className="toolbar">
        {!empty && (
          <>
            <div className="segmented" role="tablist" aria-label={t("View")}>
              <button role="tab" aria-selected={view === "steps"} className={view === "steps" ? "on" : ""}
                onClick={() => setView("steps")} data-testid="tab-steps">
                <ListIcon /> {t("Steps")}
              </button>
              <button role="tab" aria-selected={view === "graph"} className={view === "graph" ? "on" : ""}
                onClick={() => setView("graph")} data-testid="tab-graph">
                <MapIcon /> {t("Map")}
              </button>
              <button role="tab" aria-selected={view === "story"} className={view === "story" ? "on" : ""}
                onClick={() => setView("story")} data-testid="tab-story">
                <StoryIcon /> {t("Story")}
              </button>
            </div>
            <Help id="map" label={t("the three views")} wide>
              <span className="views-help">
                <b>{t("Steps")}</b> — {t("every step on a card, oldest at the top: what it is, when it was stamped, and which earlier steps it came from.")}
                <br />
                <b>{t("Map")}</b> — {t("the steps and how they connect, left to right in the order they were added.")}
                <br />
                <b>{t("Story")}</b> — {help("story")}
              </span>
              <Legend />
            </Help>
            {view !== "story" && !(view === "steps" && stepsTable) && (
              <span className="with-help">
                <label className="toggle small">
                  <input type="checkbox" checked={milestonesOnly} onChange={(e) => setMilestonesOnly(e.target.checked)}
                    data-testid="milestones-only" />
                  {t("Key steps only")}
                </label>
                <Help id="key-steps" label={t("Key steps only")}>{help("keySteps")}</Help>
              </span>
            )}
          </>
        )}
        <div className="spacer" />
        <button className="secondary" onClick={() => setDialog("quick")} disabled={!projectId}
          data-testid="quick-note-open" title={t("One line is enough: the first line is the title.")}>
          <NoteIcon /> {t("Quick note")}
        </button>
        <button className="secondary" onClick={() => setDialog("export")} disabled={steps === 0}
          data-testid="share" title={help("share")}>
          <ShareIcon /> {t("Share")}
        </button>
        <button className="primary" onClick={() => openForm()} disabled={!projectId} data-testid="new-record"
          title={help("addStep")}>
          <PlusIcon /> {t("Add a step")}
        </button>
      </nav>
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
      {status.keychain_denied && (
        <div className="banner error small" data-testid="keychain-denied">
          <span>
            {t("The {keychain} refused access, so the app has stopped asking; saving steps and automatic backups wait until you try again. Click Try again, and when the system asks, choose “Always Allow”.", { keychain: keychainName() })}
          </span>
          <button className="secondary small" onClick={retryKeychain} data-testid="keychain-retry">
            {t("Try again")}
          </button>
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
      {space === "practice" && status.sample && (
        <SampleTour key={status.installation ?? ""} sample={status.sample} onAction={tourStop}
          start={tourStart} onStarted={() => setTourStart(0)} />
      )}
      <main className={`main ${selected ? "with-detail" : ""}`}>
        <section className="canvas">
          {!empty && !tipsHidden && (
            <div className="view-tip" data-testid="view-tip">
              <span>
                {view === "graph"
                  ? t("Point at a step to see its lines · click it to open it · drag to move · scroll to zoom")
                  : view === "steps"
                    ? stepsTable ? t("Click a row to open that step") : t("Click a card to see all of that step · click a #number to go to that step")
                    : t("Click a #number to open that step")}
              </span>
              <button className="link small" onClick={hideTips} data-testid="view-tip-hide">{t("Got it")}</button>
            </div>
          )}
          {empty ? (
            <EmptyState
              projectTitle={project?.title ?? t("your research")}
              backup={status.backup}
              onAdd={openForm}
              onBackup={() => setDialog("backup")}
              space={space}
              onSample={() => resetPractice(true)}
            />
          ) : view === "steps" && graph ? (
            <Steps graph={graph} rows={timeline} selected={selected} onSelect={setSelected} keyOnly={milestonesOnly}
              table={stepsTable} onTable={setStepsTable} />
          ) : view === "story" ? (
            <Story projectId={projectId} version={version} onSelect={setSelected} />
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
      {fileOver && (
        <div className="drop-overlay" data-testid="drop-overlay">
          <div>{t("Drop the files to add them to a new step")}</div>
        </div>
      )}
      {dialog === "form" && graph && (
        <div className="modal-backdrop">
          <div className="modal">
            <RecordForm
              projectId={projectId}
              nodeTypes={status.node_types}
              relationTypes={status.relation_types}
              existing={graph.nodes}
              initialType={formType}
              initialFiles={droppedFiles}
              space={space}
              onCancel={() => setDialog(null)}
              onCreated={afterSaved}
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
      {dialog === "import" && (
        <ImportDialog projects={projects} projectId={projectId} onClose={() => setDialog(null)} onImported={reload}
          onGit={() => setDialog("git")} />
      )}
      {dialog === "git" && (
        <GitDialog projects={projects} projectId={projectId} onClose={() => setDialog(null)} onChanged={reload} />
      )}
      {dialog === "folders" && (
        <FolderDialog projects={projects} projectId={projectId} onClose={() => { setDialog(null); void reload(); }} />
      )}
      {dialog === "inbox" && (
        <InboxDialog
          nodeTypes={status.node_types}
          onClose={() => setDialog(null)}
          onRecorded={(id) => { setSelected(id); void reload(); }}
          onWatch={() => setDialog("folders")}
        />
      )}
      {dialog === "new-project" && <NewProject onClose={() => setDialog(null)} onCreated={projectCreated} />}
      {dialog === "quick" && projectId && (
        <QuickNote projects={projects} projectId={projectId} onClose={() => setDialog(null)} onSaved={afterSaved} />
      )}
      {dialog === "export" && (
        <ExportDialog rows={timeline} defaultTitle={project?.title ?? t("evidence")} onClose={() => setDialog(null)}
          practice={practice} projectId={projectId} />
      )}
      {dialog === "example-confirm" && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={t("See the example")}>
          <div className="modal" data-testid="example-confirm">
            <h2>{t("See the example")}</h2>
            <p>{t("This replaces what is in the practice space. Your real record is not touched.")}</p>
            <div className="actions">
              <button className="secondary" onClick={() => setDialog(null)}>{t("Cancel")}</button>
              <button className="primary" onClick={() => void openExample(false)} data-testid="example-confirm-yes">
                {t("Replace practice and show the example")}
              </button>
            </div>
          </div>
        </div>
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
