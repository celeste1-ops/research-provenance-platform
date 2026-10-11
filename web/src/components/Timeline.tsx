import type { TimelineRow } from "../types";
import { help, stampState, typeLabel } from "../labels";
import { t } from "../i18n";
import { Help } from "./Help";
import { ProofIcon } from "./ProofBadge";

function kindLabel(kind: string): string {
  switch (kind) {
    case "genesis":
      return t("Start (genesis)");
    case "entry":
      return t("Step");
    case "link":
      return t("Link (added later)");
    case "milestone":
      return t("Key step change");
    case "statement":
      return t("Note (added later)");
    case "retraction":
      return t("Retraction");
    default:
      return kind;
  }
}

export function relLabel(rel: string): string {
  switch (rel) {
    case "revises":
      return t("revises");
    case "derived_from":
      return t("derived from");
    case "uses":
      return t("uses");
    default:
      return rel.replace("_", " ");
  }
}

// Timeline view (PRD §11): every record in seq order; the two proofs in separate columns;
// local time in grey marked "unverified".
export function Timeline({ rows, onSelect }: { rows: TimelineRow[]; onSelect: (id: string) => void }) {
  return (
    <div className="timeline" data-testid="timeline">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>
              {t("Date stamp")} <Help id="list-tsa" label={t("a date stamp")}>{help("dateStamp")}</Help>
            </th>
            <th>
              {t("Public stamp")} <Help id="list-btc" label={t("a public stamp")}>{help("publicStamp")}</Help>
            </th>
            <th>
              {t("Local time")} <span className="unverified">{t("(unverified)")}</span>
            </th>
            <th>{t("Kind / type")}</th>
            <th>{t("Title")}</th>
            <th>{t("Relations")}</th>
            <th>{t("Source")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} onClick={() => onSelect(r.id)} className="clickable" data-testid={`row-${r.id}`}>
              <td>{r.seq}</td>
              <td data-proof="tsa">
                <ProofIcon proof={r.tsa} /> {r.tsa.state === "confirmed" ? r.tsa.time : stampState(r.tsa)}
              </td>
              <td data-proof="btc">
                <ProofIcon proof={r.btc} /> {r.btc.state === "confirmed" ? r.btc.time : stampState(r.btc)}
              </td>
              <td className="unverified">{r.local_time.value}</td>
              <td>
                {kindLabel(r.kind)}
                {r.node_type && <span className="muted"> · {typeLabel(r.node_type)}</span>}
              </td>
              <td>{r.title}</td>
              <td className="small">
                {r.relations.map((x, i) => (
                  <div key={i}>
                    {relLabel(x.rel)} {x.to_title} <span className="muted">{t("(author)")}</span>
                  </div>
                ))}
              </td>
              <td className="small">
                <span className="tag-verified">{t("verified")}</span>
                {r.relations.length > 0 && <span className="tag-author">{t("author")}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
