import { useEffect, useRef, useState } from "react";
import { api, download } from "../api";
import { dev } from "../device";
import { t, tx } from "../i18n";
import type { AiBlock, AiResult } from "../types";

// A summary written by a language model on this computer — optional (DECISIONS D-050).
// Labelled "AI inference" and kept apart from the story above, the verified records and the
// author's statements. It comes in a few short sections of points; every point must name its
// steps, and the ones that don't are flagged. The text shows up as the model writes it, and
// Stop ends it at any time.

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
  const out = [
    `# ${r.title} — ${r.label}`,
    "",
    `> ${t("AI inference, written by {model} on this computer on {date} from the story's sentences. It may be wrong and is not part of the verifiable record. Sentences that named no step, or a step not in the story, were left out.", { model: r.model, date: r.created.slice(0, 10) })}`,
    "",
  ];
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

export function AiStory({ projectId, onSelect, open, onOpen }: {
  projectId: string;
  onSelect: (id: string) => void;
  open: boolean;
  onOpen: () => void;
}) {
  const [url, setUrl] = useState("");
  const typed = useRef("");
  const [models, setModels] = useState<string[] | null>(null);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState<"models" | "writing" | null>(null);
  const [draft, setDraft] = useState("");
  const [started, setStarted] = useState(0);
  const [now, setNow] = useState(0);
  const [result, setResult] = useState<AiResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopped, setStopped] = useState(false);
  const writing = useRef<AbortController | null>(null);

  // Leaving the story stops the model: nobody would see the rest.
  useEffect(() => () => writing.current?.abort(), []);

  // Opening the panel looks for models right away at the saved address, so one click is enough.
  useEffect(() => {
    if (!open) return;
    api.aiSettings().then((s) => {
      // A late answer never replaces what the author has typed in the meantime.
      const address = typed.current || s.url;
      setUrl(address);
      setModel((chosen) => chosen || s.model);
      void findModels(address, s.model);
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

  async function write() {
    const control = new AbortController();
    writing.current = control;
    setBusy("writing");
    setError(null);
    setStopped(false);
    setResult(null);
    setDraft("");
    setStarted(Date.now());
    setNow(Date.now());
    try {
      const out = await api.aiStory({ url, model, project: projectId || undefined },
        (piece) => setDraft((d) => d + piece), control.signal);
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
          {t("Summarise with an AI model on this {device} (optional)…", { device: dev() })}
        </button>
      </p>
    );
  }
  const seconds = Math.max(0, Math.round((now - started) / 1000));
  const found = models !== null && models.length > 0;
  return (
    <section className="ai-panel" data-testid="ai-panel">
      <h3>{t("AI summary")} <span className="ai-badge">{t("AI inference")}</span></h3>
      <p className="note">
        {tx("A language model running on this {device} (for example Ollama or LM Studio) sums up the story above in a few short points. It is given only the story's sentences — titles, your reasons and notes — and nothing goes anywhere else: <b>only an address on this {device} is accepted</b>. Its text is never saved as a step, and may be wrong.", { b: (s) => <b>{s}</b> }, { device: dev() })}
      </p>
      <div className="ai-steps">
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
      {error && <p className="error">{error}</p>}
      {stopped && <p className="note" data-testid="ai-stopped">{t("Stopped. Nothing was kept.")}</p>}
      {busy === "writing" && (
        <div className="ai-progress" data-testid="ai-progress">
          <p className="small">
            <span className="spinner" aria-hidden="true" />{" "}
            {draft ? t("Writing…") : t("Starting the model… the first time it can take a minute to load.")}{" "}
            <span className="muted">{t("{time} so far", { time: clock(seconds) })}</span>
          </p>
          {draft && <Draft text={draft} />}
        </div>
      )}
      {result && (
        <div className="ai-result" data-testid="ai-result">
          <p className="ai-label">
            {t("AI inference — written by {model} on {date}. It may be wrong; check each point against its steps.", { model: result.model, date: result.created.slice(0, 10) })}
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
