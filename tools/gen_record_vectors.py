"""Write tests/vectors/records_v1.json — frozen test vectors for rprov.record/1.

Run once; afterwards tests/unit/test_vectors.py asserts the IDs never change
(AC-01). Re-running this script must not change the file: if it would, the record
format changed, which PRD §18 forbids.

    uv run python tools/gen_record_vectors.py
"""

from __future__ import annotations

import json
from pathlib import Path

from provenance_core import records as R
from provenance_core.signing import private_key_from_raw, public_key_hex, sign_record_id

OUT = Path(__file__).resolve().parent.parent / "tests" / "vectors" / "records_v1.json"

SEED = bytes(range(32))
INSTALLATION = "6f2c1e2a-3b4d-4e5f-8a9b-0c1d2e3f4a5b"
PROJECT = "1d3e5f70-8a9b-4c1d-9e2f-3a4b5c6d7e8f"


def nonce(i: int) -> str:
    return f"{i:02x}" * 32


def build_inputs() -> list[dict]:
    key = private_key_from_raw(SEED)
    body = R.normalize_text("# 数值实验 1\r\n\r\nResult: converged 🎉\r\n")
    inputs: list[dict] = [
        {"kind": "genesis", "payload": R.genesis_payload("Example Author", public_key_hex(key.public_key()),
                                                         local_time="2026-10-12T14:00:00Z", nonce=nonce(0))},
    ]
    entry1 = R.entry_payload(
        project_id=PROJECT, project_title="FSF", node_type="idea", title="第一版公式",
        content=None, author_statement="灵感来自去年的笔记", local_time="2026-10-12T14:01:00Z", nonce=nonce(1),
    )
    inputs.append({"kind": "entry", "payload": entry1})
    return inputs, body, key


def main() -> None:
    inputs, body, key = build_inputs()
    vectors = []
    prev = None
    ids: list[str] = []
    for seq, item in enumerate(inputs):
        if seq == 2:
            break
        mb, pb, rid = R.encode_record(item["kind"], INSTALLATION, seq, prev, item["payload"])
        vectors.append({"kind": item["kind"], "seq": seq, "payload": item["payload"], "manifest_jcs": mb.decode(),
                        "payload_jcs": pb.decode(), "record_id": rid, "signature": sign_record_id(key, rid).hex()})
        ids.append(rid)
        prev = rid
    # Records that reference earlier ones.
    more = [
        ("entry", R.entry_payload(
            project_id=PROJECT, project_title="FSF", node_type="experiment", title="数值实验 1",
            content={"body": R.file_descriptor(body, "text/markdown"),
                     "files": [R.file_descriptor(b"t,x\n0,1\n", "text/csv", "run1.csv")]},
            relations=[{"to": ids[1], "rel": "uses"}], milestone=True,
            local_time="2026-10-12T14:03:05Z", nonce=nonce(2))),
        ("link", R.link_payload(None, None, "derived_from", statement="后来才意识到",
                                local_time="2026-10-13T09:00:00Z", nonce=nonce(3))),
        ("milestone", R.milestone_payload(None, "unset", local_time="2026-10-13T09:01:00Z", nonce=nonce(4))),
        ("statement", R.statement_payload(None, "补充：参数取自文献", local_time="2026-10-13T09:02:00Z",
                                          nonce=nonce(5))),
        ("retraction", R.retraction_payload(None, "实验设置有误", local_time="2026-10-13T09:03:00Z",
                                            nonce=nonce(6))),
    ]
    for kind, payload in more:
        seq = len(vectors)
        if kind == "link":
            payload["from"], payload["to"] = ids[2], ids[1]
        elif kind in ("milestone", "statement", "retraction"):
            payload["target"] = ids[2]
        mb, pb, rid = R.encode_record(kind, INSTALLATION, seq, prev, payload)
        vectors.append({"kind": kind, "seq": seq, "payload": payload, "manifest_jcs": mb.decode(),
                        "payload_jcs": pb.decode(), "record_id": rid, "signature": sign_record_id(key, rid).hex()})
        ids.append(rid)
        prev = rid
    doc = {
        "schema": "rprov.record/1",
        "description": "Frozen vectors: record IDs and signatures must never change.",
        "ed25519_seed_hex": SEED.hex(),
        "installation": INSTALLATION,
        "body_text_crlf": "# 数值实验 1\r\n\r\nResult: converged 🎉\r\n",
        "body_sha256": R.sha256_hex(body),
        "records": vectors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(vectors)} vectors to {OUT}")


if __name__ == "__main__":
    main()
