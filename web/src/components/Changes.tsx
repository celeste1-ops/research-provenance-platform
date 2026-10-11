import { useEffect, useState } from "react";
import { api } from "../api";
import { t, tx } from "../i18n";

interface Diff {
  body_diff: string;
  files: Record<string, string[]>;
}

// "Changes": line diff against each record this one revises; attachments compared by hash.
export function Changes({ id, revises, titleOf }: { id: string; revises: string[]; titleOf: (id: string) => string }) {
  const [diffs, setDiffs] = useState<Record<string, Diff>>({});

  useEffect(() => {
    let live = true;
    Promise.all(revises.map((r) => api.diff(id, r).then((d) => [r, d] as const))).then((pairs) => {
      if (live) setDiffs(Object.fromEntries(pairs));
    });
    return () => {
      live = false;
    };
  }, [id, revises]);

  if (revises.length === 0) {
    return <p className="muted small">{t("This record does not revise another record.")}</p>;
  }
  return (
    <>
      {revises.map((r) => {
        const d = diffs[r];
        return (
          <div key={r} className="change">
            <div className="small">
              {tx("against <b>{title}</b>", { b: (s) => <b>{s}</b> }, { title: titleOf(r) })}
            </div>
            {!d ? (
              <p className="muted small">{t("Loading…")}</p>
            ) : (
              <>
                {d.body_diff ? (
                  <pre className="diff">
                    {d.body_diff.split("\n").map((line, i) => (
                      <div key={i} className={line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : ""}>
                        {line}
                      </div>
                    ))}
                  </pre>
                ) : (
                  <p className="muted small">{t("Body unchanged.")}</p>
                )}
                <ul className="small">
                  {(["added", "removed", "modified"] as const).map((k) =>
                    d.files[k]?.length ? (
                      <li key={k}>
                        {k === "added" ? t("added") : k === "removed" ? t("removed") : t("modified")}: {d.files[k].join(", ")}
                      </li>
                    ) : null,
                  )}
                </ul>
              </>
            )}
          </div>
        );
      })}
    </>
  );
}
