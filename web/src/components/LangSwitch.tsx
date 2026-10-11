import type { Lang } from "../i18n";

// The other language's own name, so it can be found whichever language is showing (D-046).
export function LangSwitch({ value, onChange }: { value: Lang; onChange: (l: Lang) => void }) {
  const next: Lang = value === "zh" ? "en" : "zh";
  return (
    <button
      type="button"
      className="secondary small lang-switch"
      data-testid="lang-switch"
      lang={next === "zh" ? "zh-CN" : "en"}
      title={next === "zh" ? "切换到中文" : "Switch to English"}
      onClick={() => onChange(next)}
    >
      {next === "zh" ? "中文" : "English"}
    </button>
  );
}
