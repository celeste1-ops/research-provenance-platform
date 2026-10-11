import type { ReactNode } from "react";
import { dev } from "../device";
import { t, tx } from "../i18n";

export interface SummaryItem {
  label: string;
  value: ReactNode;
}

// Shown before anything goes into the real record: what exactly will be saved, and that it
// cannot be changed or deleted afterwards (DECISIONS D-038). Practice saves skip it.
export function ConfirmReal({
  title,
  items,
  confirmLabel,
  busy = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  items: SummaryItem[];
  confirmLabel?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="confirm-real" data-testid="confirm-real" role="alertdialog" aria-label={title}>
      <h2>{title}</h2>
      <p className="warning">
        {tx("This goes into your <b>real record</b>. Once saved it can't be changed or deleted — you can only add to it or retract it later.", { b: (s) => <b>{s}</b> })}
      </p>
      {items.length > 0 && (
        <dl className="summary">
          {items.map((it) => (
            <div key={it.label} className="summary-row">
              <dt>{it.label}</dt>
              <dd>{it.value}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="note">{t("Only a fingerprint of it is sent out for the date stamp; the content stays on this {device}.", { device: dev() })}</p>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
          {t("Go back")}
        </button>
        <button type="button" className="primary" onClick={onConfirm} disabled={busy} data-testid="confirm-save">
          {busy ? t("Saving…") : (confirmLabel ?? t("Save to my record"))}
        </button>
      </div>
    </div>
  );
}

// The same check as a pop-up, for actions started outside a form (key step, link, note, retraction).
export function ConfirmRealModal(props: Parameters<typeof ConfirmReal>[0]) {
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <ConfirmReal {...props} />
      </div>
    </div>
  );
}
