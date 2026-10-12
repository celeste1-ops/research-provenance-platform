import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { dev } from "../device";
import { t } from "../i18n";
import type { Narrative, NarrativeSentence } from "../types";
import { AiStory } from "./AiStory";

// "Story" (DECISIONS D-048): the research told in sentences from fixed templates, no AI. Each
// paragraph names the step it comes from; the author's own statements are highlighted.

function chip(s: NarrativeSentence): string {
  const day = (s.date?.time ?? "").slice(0, 10);
  return `#${s.refs[0]?.seq ?? "?"} · ${day}${s.date?.verified ? " ✓" : ""}`;
}

function markdown(n: Narrative): string {
  const line = (para: NarrativeSentence[]) =>
    para
      .map((s, i) => {
        const text = s.source === "author" ? `*${s.text}*` : s.text;
        return i === 0 && s.refs.length ? `${text} [${chip(s)}]` : text;
      })
      .join(" ");
  const out = [`# ${n.title}`, "", n.intro.map((s) => s.text).join(" "), ""];
  for (const ch of n.chapters) {
    out.push(`## ${ch.heading ?? ""}`, "");
    for (const p of ch.paragraphs) out.push(line(p), "");
  }
  return out.join("\n");
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function Story({ projectId, version, onSelect }: {
  projectId: string;
  version: number;
  onSelect: (id: string) => void;
}) {
  const [story, setStory] = useState<Narrative | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const aiRef = useRef<HTMLDivElement>(null);

  // The AI summary sits below the story; the button at the top opens it and goes there.
  function openAi() {
    setAiOpen(true);
    window.requestAnimationFrame(() => aiRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  useEffect(() => {
    api.narrative(projectId || undefined).then(setStory).catch((e) => setError((e as Error).message));
  }, [projectId, version]);

  if (error) return <p className="error">{error}</p>;
  if (!story) return <div className="empty">{t("Loading…")}</div>;
  return (
    <div className="story-scroll">
    <article className="story-view" data-testid="story">
      <div className="story-tools">
        <button className="secondary small ai-jump" onClick={openAi} data-testid="ai-jump"
          title={t("Summarise with an AI model on this {device} (optional)…", { device: dev() })}>
          {t("AI summary…")}
        </button>
        <button className="secondary small" data-testid="story-markdown"
          onClick={() => download(`${story.title.replace(/[\\/:*?"<>|]+/g, "_")}.md`, markdown(story))}>
          {t("Save as Markdown")}
        </button>
        <button className="secondary small" onClick={() => window.print()}>{t("Print or save as PDF")}</button>
      </div>
      <h2>{story.title}</h2>
      <div className="story-intro note">
        {story.intro.map((s, i) => <p key={i}>{s.text}</p>)}
      </div>
      {story.chapters.map((ch, ci) => (
        <section key={ci}>
          <h3>{ch.heading}</h3>
          {ch.paragraphs.map((para, pi) => (
            <p key={pi} className="story-para" data-testid="story-para">
              {para.map((s, si) => (
                <span key={si}>
                  <span className={s.source === "author" ? "s-author" : "s-record"}>{s.text}</span>
                  {si === 0 && s.refs[0] && (
                    <>
                      {" "}
                      <button className="link ref" onClick={() => onSelect(s.refs[0].id)}
                        title={s.date?.from ?? ""} data-testid="story-ref">
                        {chip(s)}
                      </button>
                    </>
                  )}{" "}
                </span>
              ))}
            </p>
          ))}
        </section>
      ))}
      <div ref={aiRef}>
        <AiStory projectId={projectId} onSelect={onSelect} open={aiOpen} onOpen={() => setAiOpen(true)} />
      </div>
    </article>
    </div>
  );
}
