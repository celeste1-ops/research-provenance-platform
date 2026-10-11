import type { TimelineRow } from "../types";
import { HELP, TYPE_LABELS, stampState } from "../labels";
import { Help } from "./Help";
import { ProofIcon } from "./ProofBadge";

const KIND_LABELS: Record<string, string> = {
  genesis: "Start (genesis)",
  entry: "Step",
  link: "Link (added later)",
  milestone: "Key step change",
  statement: "Note (added later)",
  retraction: "Retraction",
};

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
              Date stamp <Help id="list-tsa" label="a date stamp">{HELP.dateStamp}</Help>
            </th>
            <th>
              Public stamp <Help id="list-btc" label="a public stamp">{HELP.publicStamp}</Help>
            </th>
            <th>
              Local time <span className="unverified">(unverified)</span>
            </th>
            <th>Kind / type</th>
            <th>Title</th>
            <th>Relations</th>
            <th>Source</th>
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
                {KIND_LABELS[r.kind] ?? r.kind}
                {r.node_type && <span className="muted"> · {TYPE_LABELS[r.node_type] ?? r.node_type}</span>}
              </td>
              <td>{r.title}</td>
              <td className="small">
                {r.relations.map((x, i) => (
                  <div key={i}>
                    {x.rel.replace("_", " ")} {x.to_title} <span className="muted">(author)</span>
                  </div>
                ))}
              </td>
              <td className="small">
                <span className="tag-verified">verified</span>
                {r.relations.length > 0 && <span className="tag-author">author</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
