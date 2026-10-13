import { useEffect, useRef, useState } from "react";
import { api, download } from "../api";
import { dev, keychainName } from "../device";
import { t, tn, tx } from "../i18n";
import type { AiBlock, AiResult, CloudLogEntry, CloudPreview, CloudProvider, CloudStatus } from "../types";

// A summary written by a language model — optional (DECISIONS D-050, D-061). The model runs on
// this computer, or at an online service the author connected with their own key; that service
// gets only the text the author was shown, each time, after clicking Send. Labelled
// "AI inference" and kept apart from the story above, the verified records and the author's
// statements. It comes in a few short sections of points; every point must name its steps, and
// the ones that don't are flagged. The text shows up as the model writes it, and Stop ends it at
// any time.

type Where = "local" | "cloud";

// "[#12, #15]" as the model writes it; shown as links instead (the saved text keeps it).
const CITATION = /\s*[[［【][^\]］】]*[\]］】]/g;
const EMPHASIS = /\*\*|__/g;
const BULLET = /^(?:[-*•·]\s+|\d+[.)]\s+|\d+、\s*)/;

type Sentence = Extract<AiBlock, { kind: "sentence" }>;
type Part = { item: boolean; sentences: Sentence[] };
type Section = { heading: string | null; parts: Part[] };

function problem(status: string): string {
  switch (status) {
    case "no_source":
      return t("names no step");
    case "unknown_source":
      return t("names a step that is not in the story");
    case "claim":
      return t("makes a claim the records cannot support");
    default:
      return "";
  }
}

/** Headings, points and paragraphs, in the order the model wrote them. */
function sections(blocks: AiBlock[]): Section[] {
  const out: Section[] = [];
  let section: Section | null = null;
  let part: Part | null = null;
  const current = () => {
    if (!section) {
      section = { heading: null, parts: [] };
      out.push(section);
    }
    return section;
  };
  for (const b of blocks) {
    if (b.kind === "heading") {
      section = { heading: b.text, parts: [] };
      out.push(section);
      part = null;
    } else if (b.kind === "break") {
      part = null;
    } else if (b.kind === "item") {
      part = { item: true, sentences: [] };
      current().parts.push(part);
    } else {
      if (!part) {
        part = { item: false, sentences: [] };
        current().parts.push(part);
      }
      part.sentences.push(b);
    }
  }
  return out.filter((s) => s.parts.some((p) => p.sentences.length > 0));
}

function markdown(r: AiResult): string {
  const date = r.created.slice(0, 10);
  const note = r.service
    ? t("AI inference, written by {model} at {service} on {date} from the story's sentences. It may be wrong and is not part of the verifiable record. Sentences that named no step, or a step not in the story, were left out.", { model: r.model, service: r.service, date })
    : t("AI inference, written by {model} on this computer on {date} from the story's sentences. It may be wrong and is not part of the verifiable record. Sentences that named no step, or a step not in the story, were left out.", { model: r.model, date });
  const out = [`# ${r.title} — ${r.label}`, "", `> ${note}`, ""];
  for (const s of sections(r.blocks)) {
    const parts = s.parts
      .map((p) => ({ item: p.item, text: p.sentences.filter((x) => x.status === "ok").map((x) => x.text).join(" ") }))
      .filter((p) => p.text);
    if (!parts.length) continue;
    if (s.heading) out.push(`## ${s.heading}`, "");
    for (const p of parts) out.push(p.item ? `- ${p.text}` : `${p.text}\n`);
    out.push("");
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}

function SentenceView({ b, onSelect }: { b: Sentence; onSelect: (id: string) => void }) {
  return (
    <span className={b.status === "ok" ? "ai-ok" : "ai-flagged"} data-testid={`ai-${b.status}`}
      title={problem(b.status)}>
      {b.text.replace(CITATION, "").replace(EMPHASIS, "")}
      {b.refs.filter((r) => r.id).map((r) => (
        <button key={r.seq} className="link ref" onClick={() => onSelect(r.id as string)}
          title={t("Open step #{n}", { n: r.seq })}>#{r.seq}</button>
      ))}
      {b.status !== "ok" && <em className="ai-why"> ({problem(b.status)})</em>}{" "}
    </span>
  );
}

function SectionView({ s, onSelect }: { s: Section; onSelect: (id: string) => void }) {
  const groups: Part[][] = [];
  for (const p of s.parts) {
    const last = groups[groups.length - 1];
    if (last && last[0].item && p.item) last.push(p);
    else groups.push([p]);
  }
  return (
    <section className="ai-section" data-testid="ai-section">
      {s.heading && <h4>{s.heading}</h4>}
      {groups.map((g, i) =>
        g[0].item ? (
          <ul key={i}>
            {g.map((p, j) => (
              <li key={j}>{p.sentences.map((b, k) => <SentenceView key={k} b={b} onSelect={onSelect} />)}</li>
            ))}
          </ul>
        ) : (
          <p key={i}>{g[0].sentences.map((b, k) => <SentenceView key={k} b={b} onSelect={onSelect} />)}</p>
        ),
      )}
    </section>
  );
}

/** What the model has written so far, laid out the same way, before it is checked. */
function Draft({ text }: { text: string }) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  return (
    <div className="ai-draft" data-testid="ai-draft" aria-live="polite">
      {lines.map((line, i) => {
        const clean = line.replace(CITATION, "").replace(EMPHASIS, "");
        if (line.startsWith("#")) return <h4 key={i}>{clean.replace(/^#+\s*/, "")}</h4>;
        if (BULLET.test(line)) return <div key={i} className="ai-draft-item">• {clean.replace(BULLET, "")}</div>;
        return <div key={i}>{clean}</div>;
      })}
      <span className="ai-cursor" aria-hidden="true" />
    </div>
  );
}

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

const PROVIDERS: { id: CloudProvider; name: string }[] = [
  { id: "anthropic", name: "Claude (Anthropic)" },
  { id: "deepseek", name: "DeepSeek" },
  { id: "qwen", name: "Qwen (Alibaba Cloud)" },
];

/** Connecting an online service once, with the author's own key. */
function CloudConnect({ onConnected }: { onConnected: (s: CloudStatus, models: string[]) => void }) {
  const [provider, setProvider] = useState<CloudProvider>("anthropic");
  const [key, setKey] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await api.cloudConnect(provider, key, url);
      onConnected(out, out.models);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="cloud-connect" onSubmit={connect} data-testid="cloud-connect">
      <div className="row">
        <select value={provider} onChange={(e) => setProvider(e.target.value as CloudProvider)} aria-label={t("AI service")}
          data-testid="cloud-provider">
          {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          <option value="other">{t("Another service (common chat API)")}</option>
        </select>
        {provider === "other" && (
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/v1"
            aria-label={t("Address of the service")} data-testid="cloud-url" />
        )}
      </div>
      <div className="row">
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={t("API key")}
          aria-label={t("API key")} autoComplete="off" data-testid="cloud-key" />
        <button className="secondary" disabled={busy || key.trim().length < 8 || (provider === "other" && !url.trim())}
          data-testid="cloud-connect-button">
          {busy ? t("Checking…") : t("Connect")}
        </button>
      </div>
      <p className="note">
        {t("Make an API key on the service's website and paste it here. It is kept in the {keychain} and sent only to that service, which charges each summary to the key's account.", { keychain: keychainName() })}
      </p>
      {error && <p className="error small">{error}</p>}
    </form>
  );
}

/** Everything that was sent to an online service, newest first: the author can always look. */
function CloudLog({ onClose }: { onClose: () => void }) {
  const [log, setLog] = useState<{ count: number; entries: CloudLogEntry[] } | null>(null);
  useEffect(() => {
    api.cloudLog().then(setLog).catch(() => setLog({ count: 0, entries: [] }));
  }, []);
  return (
    <div className="cloud-log" data-testid="cloud-log">
      <div className="row">
        <b>{t("What was sent to online AI services")}</b>
        <span className="spacer" />
        <button className="link small" onClick={onClose}>{t("Close")}</button>
      </div>
      {log && log.count === 0 && <p className="small muted">{t("Nothing has been sent yet.")}</p>}
      {log && log.count > log.entries.length && (
        <p className="small muted">{t("The latest {n} of {count} are shown; all of them are in ai-sent.jsonl in the data folder.", { n: log.entries.length, count: log.count })}</p>
      )}
      {log?.entries.map((e) => (
        <details key={e.fingerprint + e.time} className="cloud-log-entry">
          <summary>
            {e.time.slice(0, 16).replace("T", " ")} · {e.service} · {e.model} · {e.title}
            {e.space === "practice" && ` · ${t("Practice")}`} · {tn(e.characters, "{n} character", "{n} characters")}
          </summary>
          <pre className="cloud-text">{e.system}</pre>
          <pre className="cloud-text">{e.user}</pre>
        </details>
      ))}
    </div>
  );
}

export function AiStory({ projectId, onSelect, open, onOpen }: {
  projectId: string;
  onSelect: (id: string) => void;
  open: boolean;
  onOpen: () => void;
}) {
  const [where, setWhere] = useState<Where>("local");
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [cloudModels, setCloudModels] = useState<string[]>([]);
  const [cloudModel, setCloudModel] = useState("");
  const [preview, setPreview] = useState<CloudPreview | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [url, setUrl] = useState("");
  const typed = useRef("");
  const [models, setModels] = useState<string[] | null>(null);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState<"models" | "writing" | "preview" | null>(null);
  const [draft, setDraft] = useState("");
  const [started, setStarted] = useState(0);
  const [now, setNow] = useState(0);
  const [result, setResult] = useState<AiResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopped, setStopped] = useState(false);
  const writing = useRef<AbortController | null>(null);

  // Leaving the story stops the model: nobody would see the rest.
  useEffect(() => () => writing.current?.abort(), []);

  // Opening the panel looks for models right away at the saved address, so one click is enough —
  // or, once an online service is connected, opens on that (still nothing is sent before Send).
  useEffect(() => {
    if (!open) return;
    api.aiSettings().then((s) => {
      setCloud(s.cloud);
      // A late answer never replaces what the author has typed in the meantime.
      const address = typed.current || s.url;
      setUrl(address);
      setModel((chosen) => chosen || s.model);
      if (s.cloud.connected) {
        setWhere("cloud");
        setCloudModel((chosen) => chosen || s.cloud.model || (s.cloud.connected ? s.cloud.default_model : ""));
      } else {
        void findModels(address, s.model);
      }
    }).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (busy !== "writing") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  async function findModels(address = url, preferred = model) {
    setBusy("models");
    setError(null);
    try {
      const out = await api.aiModels(address);
      setUrl(out.url);
      setModels(out.models);
      setModel((chosen) => (out.models.includes(chosen) ? chosen : out.models.includes(preferred) ? preferred : out.models[0] ?? ""));
    } catch (e) {
      setModels(null);
      setError((e as Error).message);
    } finally {
      setBusy((b) => (b === "models" ? null : b));
    }
  }

  function choose(next: Where) {
    setWhere(next);
    setError(null);
    setPreview(null);
    if (next === "local" && models === null && url) void findModels();
  }

  async function findCloudModels() {
    setBusy("models");
    setError(null);
    try {
      setCloudModels((await api.cloudModels()).models);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy((b) => (b === "models" ? null : b));
    }
  }

  async function look() {
    setBusy("preview");
    setError(null);
    setResult(null);
    try {
      setPreview(await api.cloudPreview(cloudModel.trim(), projectId || undefined));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy((b) => (b === "preview" ? null : b));
    }
  }

  async function disconnect() {
    try {
      setCloud(await api.cloudForget());
      setPreview(null);
      setCloudModels([]);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function write() {
    const sent = where === "cloud" ? preview : null;
    if (where === "cloud" && !sent) return;
    const control = new AbortController();
    writing.current = control;
    setBusy("writing");
    setError(null);
    setStopped(false);
    setResult(null);
    setDraft("");
    setPreview(null);
    setStarted(Date.now());
    setNow(Date.now());
    try {
      const body = sent
        ? { mode: "cloud" as const, model: sent.model, confirm: sent.fingerprint, project: projectId || undefined }
        : { url, model, project: projectId || undefined };
      const out = await api.aiStory(body, (piece) => setDraft((d) => d + piece), control.signal);
      setResult(out);
    } catch (e) {
      if (control.signal.aborted) setStopped(true);
      else setError((e as Error).message);
    } finally {
      writing.current = null;
      setDraft("");
      setBusy(null);
    }
  }

  if (!open) {
    return (
      <p className="ai-open">
        <button className="link small" onClick={onOpen} data-testid="ai-open">
          {t("Summarise with an AI model (optional)…")}
        </button>
      </p>
    );
  }
  const seconds = Math.max(0, Math.round((now - started) / 1000));
  const found = models !== null && models.length > 0;
  const service = cloud?.connected ? cloud.service : "";
  return (
    <section className="ai-panel" data-testid="ai-panel">
      <h3>{t("AI summary")} <span className="ai-badge">{t("AI inference")}</span></h3>
      <div className="segmented small" role="tablist" aria-label={t("Where the model runs")}>
        <button role="tab" aria-selected={where === "local"} className={where === "local" ? "on" : ""}
          onClick={() => choose("local")} disabled={busy === "writing"} data-testid="ai-where-local">
          {t("On this {device}", { device: dev() })}
        </button>
        <button role="tab" aria-selected={where === "cloud"} className={where === "cloud" ? "on" : ""}
          onClick={() => choose("cloud")} disabled={busy === "writing"} data-testid="ai-where-cloud">
          {t("Online AI service")}
        </button>
      </div>
      {where === "cloud" ? (
        <div className="ai-steps" data-testid="ai-cloud">
          <p className="note">
            {tx("An online service writes the summary instead. <b>Nothing is sent until you have seen it and clicked Send</b>, every time. What is sent is the story's sentences — titles, your reasons and notes, the names of attached files, dates — never the text of a step or what its files hold. The service then has it, under its own rules.", { b: (s) => <b>{s}</b> })}
          </p>
          {cloud && !cloud.connected && (
            <CloudConnect onConnected={(s, list) => {
              setCloud(s);
              setCloudModels(list);
              if (s.connected) setCloudModel(s.default_model || list[0] || "");
            }} />
          )}
          {cloud?.connected && (
            <>
              <p className="small" data-testid="cloud-connected">
                {t("Connected to {service} ({host}).", { service: cloud.service, host: cloud.host })}{" "}
                <button className="link small" onClick={disconnect} data-testid="cloud-disconnect">{t("Disconnect")}</button>
                {" · "}
                <button className="link small" onClick={() => setShowLog(!showLog)} data-testid="cloud-log-open">
                  {t("What was sent")}
                </button>
              </p>
              <div className="row">
                <span className="ai-step-no">1</span>
                <input value={cloudModel} list="cloud-models" onChange={(e) => { setCloudModel(e.target.value); setPreview(null); }}
                  aria-label={t("Model")} data-testid="cloud-model" disabled={busy === "writing"} />
                <datalist id="cloud-models">{cloudModels.map((m) => <option key={m} value={m} />)}</datalist>
                <button className="secondary" onClick={findCloudModels} disabled={busy !== null}>
                  {busy === "models" ? t("Looking…") : t("Find models")}
                </button>
              </div>
              <div className="row">
                <span className="ai-step-no">2</span>
                {busy === "writing" ? (
                  <button className="secondary" onClick={() => writing.current?.abort()} data-testid="ai-stop">{t("Stop")}</button>
                ) : (
                  <button className="primary" onClick={look} disabled={busy !== null || !cloudModel.trim()} data-testid="cloud-look">
                    {busy === "preview" ? t("Looking…") : t("Look at what will be sent…")}
                  </button>
                )}
              </div>
              {preview && (
                <div className="cloud-preview" data-testid="cloud-preview">
                  <p className="small">
                    {tx("This is exactly what goes to <b>{service}</b> ({host}), for {model} — {n} characters:", { b: (c) => <b>{c}</b> },
                      { service: preview.service, host: preview.host, model: preview.model, n: preview.characters })}
                  </p>
                  <pre className="cloud-text" data-testid="cloud-preview-system">{preview.system}</pre>
                  <pre className="cloud-text" data-testid="cloud-preview-user">{preview.user}</pre>
                  <p className="warning small">{t("Once sent, the service has this text; it cannot be taken back. It is also written to the log on this {device}.", { device: dev() })}</p>
                  <div className="actions start">
                    <button className="secondary" onClick={() => setPreview(null)}>{t("Cancel")}</button>
                    <button className="primary" onClick={write} data-testid="cloud-send">
                      {t("Send to {service} and write the summary", { service: preview.service })}
                    </button>
                  </div>
                </div>
              )}
              {showLog && <CloudLog onClose={() => setShowLog(false)} />}
            </>
          )}
        </div>
      ) : (
      <div className="ai-steps">
        <p className="note">
          {tx("A language model running on this {device} (for example Ollama or LM Studio) sums up the story above in a few short points. It is given only the story's sentences — titles, your reasons and notes — and nothing goes anywhere else: <b>only an address on this {device} is accepted</b>. Its text is never saved as a step, and may be wrong.", { b: (s) => <b>{s}</b> }, { device: dev() })}
        </p>
        <div className="row">
          <span className="ai-step-no">1</span>
          <input value={url} onChange={(e) => { typed.current = e.target.value; setUrl(e.target.value); setModels(null); }}
            aria-label={t("Address of the local model")} data-testid="ai-url" />
          <button className="secondary" onClick={() => findModels()} disabled={busy !== null || !url.trim()} data-testid="ai-find">
            {busy === "models" ? t("Looking…") : models === null ? t("Find models") : t("Look again")}
          </button>
        </div>
        {models && models.length === 0 && <p className="warning">{t("The server is running but offers no model yet.")}</p>}
        {!found && error && busy !== "writing" && (
          <p className="note">{t("Start Ollama or LM Studio on this {device}, then click Look again.", { device: dev() })}</p>
        )}
        {found && (
          <div className="row">
            <span className="ai-step-no">2</span>
            <select value={model} onChange={(e) => setModel(e.target.value)} aria-label={t("Model")} data-testid="ai-model"
              disabled={busy === "writing"}>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            {busy === "writing" ? (
              <button className="secondary" onClick={() => writing.current?.abort()} data-testid="ai-stop">
                {t("Stop")}
              </button>
            ) : (
              <button className="primary" onClick={write} disabled={busy !== null || !model} data-testid="ai-write">
                {result ? t("Write again") : t("Write the summary")}
              </button>
            )}
          </div>
        )}
        {found && busy !== "writing" && !result && (
          <p className="note">{t("A local model usually needs one to three minutes. You see the text appear as it is written, and can stop at any time.")}</p>
        )}
      </div>
      )}
      {error && <p className="error">{error}</p>}
      {stopped && <p className="note" data-testid="ai-stopped">{t("Stopped. Nothing was kept.")}</p>}
      {busy === "writing" && (
        <div className="ai-progress" data-testid="ai-progress">
          <p className="small">
            <span className="spinner" aria-hidden="true" />{" "}
            {draft ? t("Writing…") : where === "cloud" ? t("Waiting for {service}…", { service })
              : t("Starting the model… the first time it can take a minute to load.")}{" "}
            <span className="muted">{t("{time} so far", { time: clock(seconds) })}</span>
          </p>
          {draft && <Draft text={draft} />}
        </div>
      )}
      {result && (
        <div className="ai-result" data-testid="ai-result">
          <p className="ai-label">
            {result.service
              ? t("AI inference — written by {model} at {service} on {date}. It may be wrong; check each point against its steps.", { model: result.model, service: result.service, date: result.created.slice(0, 10) })
              : t("AI inference — written by {model} on {date}. It may be wrong; check each point against its steps.", { model: result.model, date: result.created.slice(0, 10) })}
          </p>
          <p className="small muted" data-testid="ai-counts">
            {result.counts.flagged === 0
              ? t("Every sentence names its steps — click a #number to check it.")
              : t("{ok} sentences name their steps; {flagged} flagged (crossed out, left out when saving).", result.counts)}
          </p>
          <div className="ai-text">
            {sections(result.blocks).map((s, i) => <SectionView key={i} s={s} onSelect={onSelect} />)}
          </div>
          <button className="secondary small" data-testid="ai-markdown" onClick={() => {
            const blob = new Blob([markdown(result)], { type: "text/markdown;charset=utf-8" });
            download(blob, `${result.title.replace(/[\\/:*?"<>|]+/g, "_")} - AI.md`);
          }}>
            {t("Save as Markdown (labelled AI inference)")}
          </button>
        </div>
      )}
    </section>
  );
}
