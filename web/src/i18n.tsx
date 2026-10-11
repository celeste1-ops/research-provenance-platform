import type { ReactNode } from "react";
import { ZH } from "./locales/zh";

// Interface language (DECISIONS D-046). The English text is the key: t("Save step") gives the
// Chinese from locales/zh.ts, or the English itself when no translation exists. Keys must be
// plain string literals so tests/unit/test_i18n.py can check that every one is translated.

export type Lang = "en" | "zh";
const STORE_KEY = "rprov-lang";

function detect(): Lang {
  try {
    const saved = window.localStorage.getItem(STORE_KEY);
    if (saved === "en" || saved === "zh") return saved;
  } catch {
    /* storage unavailable */
  }
  const langs = navigator.languages?.length ? navigator.languages : [navigator.language];
  return langs.some((l) => l?.toLowerCase().startsWith("zh")) ? "zh" : "en";
}

let current: Lang = typeof window === "undefined" ? "en" : detect();

export function lang(): Lang {
  return current;
}

export function setLang(next: Lang): void {
  current = next;
  try {
    window.localStorage.setItem(STORE_KEY, next);
  } catch {
    /* storage unavailable */
  }
  document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
}

type Params = Record<string, string | number>;

// Chinese next to Latin letters or digits reads better with a space between them.
function spaced(s: string): string {
  return s
    .replace(/([\u3400-\u9fff])([A-Za-z0-9])/g, "$1 $2")
    .replace(/([A-Za-z0-9%])([\u3400-\u9fff])/g, "$1 $2");
}

export function t(en: string, params?: Params): string {
  const text = current === "zh" ? (ZH[en] ?? en) : en;
  const filled = params
    ? text.replace(/\{(\w+)\}/g, (m: string, k: string) => (k in params ? String(params[k]) : m))
    : text;
  return current === "zh" ? spaced(filled) : filled;
}

/** Like t(), for text with markup: tx("Turn it <b>on</b>", { b: (s) => <b>{s}</b> }). */
export function tx(en: string, tags: Record<string, (inner: string) => ReactNode>, params?: Params): ReactNode[] {
  const text = t(en, params);
  const out: ReactNode[] = [];
  const re = /<(\w+)>(.*?)<\/\1>/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const render = tags[m[1]];
    out.push(<span key={i++}>{render ? render(m[2]) : m[2]}</span>);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Numbers of things: English needs singular and plural, Chinese does not. */
export function tn(n: number, one: string, many: string, params?: Params): string {
  return t(n === 1 ? one : many, { n, ...params });
}

if (typeof document !== "undefined") document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
