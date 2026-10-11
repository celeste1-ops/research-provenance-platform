import { useEffect, useState } from "react";
import { api } from "../api";
import { dev } from "../device";
import { t, tx } from "../i18n";
import type { AiBlock, AiResult } from "../types";

// Retelling the story with a language model on this computer — optional (DECISIONS D-050).
// Labelled "AI inference" and kept apart from the story above, the verified records and the
// author's statements. Every sentence must name its steps; the ones that don't are flagged.

// "[#12, #15]" as the model writes it; shown as links instead (the saved text keeps it).
const CITATION = /\s*[[［【][^\]］】]*[\]］】]/g;

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

function markdown(r: AiResult): string {
  const out = [
    `# ${r.title} — ${r.label}`,
    "",
    `> ${t("AI inference, written by {model} on this computer on {date} from the story's sentences. It may be wrong and is not part of the verifiable record. Sentences that named no step, or a step not in the story, were left out.", { model: r.model, date: r.created.slice(0, 10) })}`,
    "",
  ];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push(para.join(" "), "");
    para = [];
  };
  for (const b of r.blocks) {
    if (b.kind === "heading") {
      flush();
      out.push(`## ${b.text}`, "");
    } else if (b.kind === "break") {
      flush();
    } else if (b.status === "ok") {
      para.push(b.text);
    }
  }
  flush();
  return out.join("\n");
}

function Sentence({ b, onSelect }: { b: Extract<AiBlock, { kind: "sentence" }>; onSelect: (id: string) => void }) {
  return (
    <span className={b.status === "ok" ? "ai-ok" : "ai-flagged"} data-testid={`ai-${b.status}`}
      title={problem(b.status)}>
      {b.text.replace(CITATION, "")}
      {b.refs.filter((r) => r.id).map((r) => (
        <button key={r.seq} className="link ref" onClick={() => onSelect(r.id as string)}>#{r.seq}</button>
      ))}
      {b.status !== "ok" && <em className="ai-why"> ({problem(b.status)})</em>}{" "}
    </span>
  );
}

export function AiStory({ projectId, onSelect }: { projectId: string; onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [models, setModels] = useState<string[] | null>(null);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState<"models" | "writing" | null>(null);
  const [result, setResult] = useState<AiResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    api.aiSettings().then((s) => {
      // A late answer never replaces what the author has typed in the meantime.
      setUrl((typed) => typed || s.url);
      setModel((chosen) => chosen || s.model);
    }).catch(() => undefined);
  }, [open]);

  async function findModels() {
    setBusy("models");
    setError(null);
    try {
      const out = await api.aiModels(url);
      setUrl(out.url);
      setModels(out.models);
      if (!out.models.includes(model)) setModel(out.models[0] ?? "");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function write() {
    setBusy("writing");
    setError(null);
    try {
      setResult(await api.aiStory({ url, model, project: projectId || undefined }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!open) {
    return (
      <p className="ai-open">
        <button className="link small" onClick={() => setOpen(true)} data-testid="ai-open">
          {t("Retell with an AI model on this {device} (optional)…", { device: dev() })}
        </button>
      </p>
    );
  }
  return (
    <section className="ai-panel" data-testid="ai-panel">
      <h3>{t("AI inference")} <span className="muted small">{t("(optional)")}</span></h3>
      <p className="note">
        {tx("A language model running on this {device} (for example Ollama or LM Studio) retells the story above. It is given only the story's sentences — titles, your reasons and notes — and nothing goes anywhere else: <b>only an address on this {device} is accepted</b>. Its text is labelled AI inference, is never saved as a step, and may be wrong.", { b: (s) => <b>{s}</b> }, { device: dev() })}
      </p>
      <div className="row">
        <input value={url} onChange={(e) => { setUrl(e.target.value); setModels(null); }}
          aria-label={t("Address of the local model")} data-testid="ai-url" />
        <button className="secondary" onClick={findModels} disabled={busy !== null || !url.trim()} data-testid="ai-find">
          {busy === "models" ? t("Looking…") : t("Find models")}
        </button>
      </div>
      {models && models.length === 0 && <p className="warning">{t("The server is running but offers no model yet.")}</p>}
      {models && models.length > 0 && (
        <div className="row">
          <select value={model} onChange={(e) => setModel(e.target.value)} aria-label={t("Model")} data-testid="ai-model">
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <button className="primary" onClick={write} disabled={busy !== null || !model} data-testid="ai-write">
            {busy === "writing" ? t("Writing… a local model can take a few minutes") : t("Write")}
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="ai-result" data-testid="ai-result">
          <p className="ai-label">
            {t("AI inference — written by {model} on {date}. It may be wrong; check each sentence against its steps.", { model: result.model, date: result.created.slice(0, 10) })}
          </p>
          <p className="small" data-testid="ai-counts">
            {t("{ok} sentences name their steps; {flagged} flagged (crossed out, left out when saving).", result.counts)}
          </p>
          <div className="ai-text">
            {result.blocks.map((b, i) =>
              b.kind === "heading" ? <h4 key={i}>{b.text}</h4>
                : b.kind === "break" ? <br key={i} />
                  : <Sentence key={i} b={b} onSelect={onSelect} />,
            )}
          </div>
          <button className="secondary small" data-testid="ai-markdown" onClick={() => {
            const blob = new Blob([markdown(result)], { type: "text/markdown;charset=utf-8" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `${result.title.replace(/[\\/:*?"<>|]+/g, "_")} - AI.md`;
            a.click();
            URL.revokeObjectURL(a.href);
          }}>
            {t("Save as Markdown (labelled AI inference)")}
          </button>
        </div>
      )}
    </section>
  );
}
