"""The installation's log chain (PRD §8, V6).

Every record names its ``seq`` and the ID of the record before it (``prev``), so
the records form one hash-linked chain starting at the genesis record (seq 0).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChainIssue:
    code: str  # LOG_GAP | LOG_PREV_MISMATCH
    record_id: str | None
    message: str


def next_position(last_id: str | None, last_seq: int | None) -> tuple[int, str | None]:
    """(seq, prev) for the next record appended after (last_id, last_seq)."""
    if last_id is None:
        return 0, None
    return (last_seq or 0) + 1, last_id


def check_chain(listed_ids: list[str], manifests: dict[str, dict | None]) -> list[ChainIssue]:
    """V6: ``seq`` runs 0, 1, 2 … without gaps and each ``prev`` is the previous ID.

    ``listed_ids`` is the declared order (``chain.json``); ``manifests`` maps each
    record ID to its parsed manifest, or None when the manifest is missing or broken.
    The order is derived from the manifests themselves (they are hash-bound to their
    IDs); the declared list must agree with it.
    """
    issues: list[ChainIssue] = []
    by_seq: dict[int, str] = {}
    for rid in listed_ids:
        m = manifests.get(rid)
        if m is None:
            issues.append(ChainIssue("LOG_GAP", rid, "manifest is missing or unreadable"))
            continue
        seq = m.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            continue  # reported as SCHEMA_INVALID elsewhere
        if seq in by_seq:
            issues.append(ChainIssue("LOG_PREV_MISMATCH", rid, f"two records claim seq {seq}"))
            continue
        by_seq[seq] = rid
    for rid in manifests:
        if rid not in listed_ids:
            issues.append(ChainIssue("LOG_PREV_MISMATCH", rid, "record is not listed in the chain"))
    if not by_seq:
        return issues
    top = max(by_seq)
    for seq in range(top + 1):
        if seq not in by_seq:
            nxt = by_seq.get(seq + 1)
            issues.append(ChainIssue("LOG_GAP", nxt, f"no record with seq {seq}"))
    for seq, rid in sorted(by_seq.items()):
        prev = manifests[rid].get("prev")  # type: ignore[union-attr]
        if seq == 0:
            if prev is not None:
                issues.append(ChainIssue("LOG_PREV_MISMATCH", rid, "seq 0 must have prev = null"))
            continue
        expected = by_seq.get(seq - 1)
        if expected is not None and prev != expected:
            issues.append(
                ChainIssue("LOG_PREV_MISMATCH", rid, f"prev does not point at the record with seq {seq - 1}")
            )
    for pos, rid in enumerate(listed_ids):
        m = manifests.get(rid)
        if m is not None and isinstance(m.get("seq"), int) and m["seq"] != pos:
            issues.append(
                ChainIssue("LOG_PREV_MISMATCH", rid, f"listed at position {pos} but has seq {m['seq']}")
            )
    return issues
