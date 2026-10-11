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

// True when the language was chosen in this browser, not guessed from its settings.
export function chosenHere(): boolean {
  try {
    const saved = window.localStorage.getItem(STORE_KEY);
    return saved === "en" || saved === "zh";
  } catch {
    return false;
  }
}

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

const CJK = /[\u3400-\u9fff]/;
const LATIN = /[A-Za-z0-9%]/;

// Chinese next to Latin letters or digits reads better with a space between them.
function spaced(s: string): string {
  return s
    .replace(/([\u3400-\u9fff])([A-Za-z0-9])/g, "$1 $2")
    .replace(/([A-Za-z0-9%])([\u3400-\u9fff])/g, "$1 $2");
}

function template(en: string): string {
  return current === "zh" ? (ZH[en] ?? en) : en;
}

// Fills {name} placeholders. In Chinese, the app's own words are spaced and a space is put where
// an inserted value meets them; the values themselves (often the author's words) stay as written.
function fill(text: string, params?: Params): string {
  const zh = current === "zh";
  if (!params) return zh ? spaced(text) : text;
  let out = "";
  const add = (piece: string) => {
    if (zh && out && piece) {
      const a = out[out.length - 1];
      const b = piece[0];
      if ((CJK.test(a) && LATIN.test(b)) || (LATIN.test(a) && CJK.test(b))) out += " ";
    }
    out += piece;
  };
  const parts = text.split(/\{(\w+)\}/);
  parts.forEach((part, i) => {
    if (i % 2 === 0) add(zh ? spaced(part) : part);
    else add(part in params ? String(params[part]) : `{${part}}`);
  });
  return out;
}

export function t(en: string, params?: Params): string {
  return fill(template(en), params);
}

/** Like t(), for text with markup: tx("Turn it <b>on</b>", { b: (s) => <b>{s}</b> }). The markup
 * comes from the template only; values (which may be the author's text) are filled in afterwards. */
export function tx(en: string, tags: Record<string, (inner: string) => ReactNode>, params?: Params): ReactNode[] {
  const text = template(en);
  const out: ReactNode[] = [];
  const re = /<(\w+)>(.*?)<\/\1>/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(fill(text.slice(last, m.index), params));
    const render = tags[m[1]];
    const inner = fill(m[2], params);
    out.push(<span key={i++}>{render ? render(inner) : inner}</span>);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(fill(text.slice(last), params));
  return out;
}

/** The space between two sentences: English needs one, Chinese does not. */
export function gap(): string {
  return current === "zh" ? "" : " ";
}

/** Numbers of things: English needs singular and plural, Chinese does not. */
export function tn(n: number, one: string, many: string, params?: Params): string {
  return t(n === 1 ? one : many, { n, ...params });
}

if (typeof document !== "undefined") document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
