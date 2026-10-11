import { useState } from "react";
import { api } from "../api";
import { dev } from "../device";
import type { ServiceCheck, ServiceCheckResult } from "../types";

// “Check stamp services” (DECISIONS D-045): can this computer reach the public services the
// stamps come from? Useful where some are blocked or slow. Runs only when asked.

const GROUPS: { key: ServiceCheck["group"]; title: string; why: string }[] = [
  {
    key: "tsa",
    title: "Date stamp services",
    why: "Each step needs one of these. The app asks FreeTSA first and DigiCert when FreeTSA can't be reached.",
  },
  {
    key: "calendar",
    title: "Public stamp (Bitcoin) services",
    why: "At least 2 of these 4 must answer for a public stamp to start.",
  },
  {
    key: "explorer",
    title: "Bitcoin block checkers",
    why: "Used to check a finished public stamp. Both must answer and agree.",
  },
];

function summary(result: ServiceCheckResult): { text: string; ok: boolean }[] {
  const ok = (g: ServiceCheck["group"]) => result.checks.filter((c) => c.group === g && c.ok);
  const out: { text: string; ok: boolean }[] = [];
  if (result.in_use.tsa.length === 0) {
    out.push({ text: "Date stamps are turned off in this app's settings.", ok: true });
  } else {
    const working = ok("tsa").map((c) => c.name);
    out.push(
      working.length > 0
        ? { text: `Date stamps work (${working.join(" and ")} answered).`, ok: true }
        : {
            text:
              "Date stamps can't be reached right now. Steps are still saved; their date stamp is added " +
              "automatically as soon as a service answers.",
            ok: false,
          },
    );
  }
  if (result.in_use.btc) {
    const n = ok("calendar").length;
    out.push(
      n >= 2
        ? { text: `Public stamps can start (${n} of 4 services answered).`, ok: true }
        : {
            text: `Public stamps can't start right now (${n} of 4 answered, 2 needed). They are retried automatically.`,
            ok: false,
          },
    );
  }
  if (result.in_use.explorers) {
    const n = ok("explorer").length;
    out.push(
      n >= 2
        ? { text: "Finished public stamps can be checked.", ok: true }
        : {
            text: "Finished public stamps can't be checked from here right now; they stay “waiting” until they can.",
            ok: false,
          },
    );
  }
  return out;
}

export function ServiceCheckDialog({ onClose }: { onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ServiceCheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.networkCheck());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const lines = result ? summary(result) : [];
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Check stamp services">
      <div className="modal" data-testid="service-check">
        <div className="modal-head">
          <h2>Check stamp services</h2>
          <button className="link" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <p>
          Your stamps come from a few public services on the internet. In some places (for example in mainland China)
          some of them can be blocked or slow. This check tries each one from this {dev()}.
        </p>
        <p className="note">
          What is sent: a random test value to each service — nothing from your notes. It takes at most about half a minute.
        </p>
        <div className="actions start">
          <button className="primary" onClick={run} disabled={busy} data-testid="service-check-run">
            {busy ? "Checking…" : result ? "Check again" : "Check now"}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        {result && (
          <>
            <div className="status-box service-summary" data-testid="service-check-summary">
              {lines.map((l) => (
                <p key={l.text} className={l.ok ? "" : "warning"}>
                  {l.ok ? "✓" : "✗"} {l.text}
                </p>
              ))}
            </div>
            {GROUPS.map((g) => {
              const rows = result.checks.filter((c) => c.group === g.key);
              if (rows.length === 0) return null;
              return (
                <div key={g.key} className="group">
                  <b>{g.title}</b>
                  <p className="note why">{g.why}</p>
                  <table className="export-table service-table">
                    <tbody>
                      {rows.map((c) => (
                        <tr key={c.name} data-testid={`service-${c.name}`}>
                          <td className={c.ok ? "" : "error"}>{c.ok ? "✓" : "✗"}</td>
                          <td>{c.name}</td>
                          <td className="muted">{c.detail}</td>
                          <td className="muted">{c.ms !== null ? `${(c.ms / 1000).toFixed(1)} s` : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
            {lines.some((l) => !l.ok) && (
              <p className="note">
                Nothing is lost while a service can't be reached: steps are saved on this {dev()} right away and the
                missing stamps are fetched automatically later. You can also try again on a different network.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
