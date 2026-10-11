import { useEffect, useRef, useState, type ReactNode } from "react";
import { t } from "../i18n";

// A small "?" next to a word; click it for a one-sentence explanation.
export function Help({
  id,
  label,
  children,
  align = "left",
  wide = false,
}: {
  id: string;
  label: string;
  children: ReactNode;
  align?: "left" | "right";
  wide?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <span className="help" ref={ref}>
      <button
        type="button"
        className="help-btn"
        aria-label={t("What is {label}?", { label })}
        aria-expanded={open}
        data-testid={`help-${id}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(!open);
        }}
      >
        ?
      </button>
      {open && (
        <span className={`help-pop ${align} ${wide ? "wide" : ""}`} role="tooltip" data-testid={`help-${id}-text`}>
          {children}
        </span>
      )}
    </span>
  );
}
