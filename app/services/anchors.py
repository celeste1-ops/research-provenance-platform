"""Time proofs for records: submit after commit, retry with exponential backoff,
upgrade pending Bitcoin anchors (PRD §9 实现要求).

Time proofs are not records: their status may change. A failure here never
affects the record itself; a record without any proof shows "No timestamp yet".
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import WRITE_LOCK, AnchorRow, RecordRow
from provenance_core.providers.base import ProviderUnavailable, TimestampProvider

log = logging.getLogger("rprov.anchors")

BACKOFF_BASE = timedelta(minutes=1)
BACKOFF_MAX = timedelta(hours=6)
MAX_ATTEMPTS_BEFORE_FAILED = 30
# Saving waits for the stamps. A service that could not be reached a moment ago (blocked,
# offline) is not waited for again on the next saves for this long; the retry job and
# "Check stamps now" still try it (D-045).
SKIP_AFTER_UNREACHABLE_SECONDS = 600.0


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def backoff_delay(attempts: int) -> timedelta:
    exponent = min(max(0, attempts - 1), 20)  # 2**20 minutes is far beyond the cap
    return min(BACKOFF_BASE * (2**exponent), BACKOFF_MAX)


class AnchorService:
    def __init__(self, sessions: sessionmaker, providers: dict[str, TimestampProvider | None]):
        self.sessions = sessions
        self.providers = providers  # {"tsa": provider|None, "btc": provider|None}
        self._lock = threading.Lock()
        self._unreachable_at: dict[str, float] = {}  # kind -> time.monotonic() of the last failure

    def recently_unreachable(self, kind: str) -> bool:
        at = self._unreachable_at.get(kind)
        return at is not None and time.monotonic() - at < SKIP_AFTER_UNREACHABLE_SECONDS

    def enabled(self) -> dict[str, TimestampProvider]:
        return {k: p for k, p in self.providers.items() if p is not None}

    # ------------------------------------------------------------------ submit

    def submit_for(self, record_id: str) -> None:
        """Request every enabled kind of proof for a freshly committed record."""
        with self._lock:
            with WRITE_LOCK, self.sessions.begin() as s:
                rec = s.get(RecordRow, record_id)
                manifest = rec.manifest_bytes
                for kind, provider in self.enabled().items():
                    row = s.scalar(select(AnchorRow).where(AnchorRow.record_id == record_id, AnchorRow.provider == kind))
                    if row is None:
                        row = AnchorRow(
                            record_id=record_id,
                            provider=kind,
                            provider_name=provider.name,
                            status="pending",
                            attempts=0,
                            detail="",
                            updated_local=_iso(_now()),
                        )
                        s.add(row)
            for kind in self.enabled():
                if self.recently_unreachable(kind):
                    log.info("%s service unreachable a moment ago: not waiting for it; it is retried later", kind)
                    continue  # the row stays pending and due, so the next refresh picks it up
                self._attempt(record_id, kind, manifest)

    def _attempt(self, record_id: str, kind: str, manifest: bytes) -> None:
        provider = self.providers[kind]
        assert provider is not None
        error: str | None = None
        result = None
        try:
            result = provider.submit(record_id, manifest)
            if result.status == "confirmed":
                check = provider.verify(record_id, result.proof)
                if not check.verified:
                    raise ValueError(f"provider returned an invalid proof: {check.code} {check.detail}")
        except Exception as exc:  # noqa: BLE001 - every failure goes to the retry queue
            error = f"{type(exc).__name__}: {exc}"
            log.info("%s proof for %s not obtained: %s", kind, record_id[:12], error)
            if isinstance(exc, ProviderUnavailable):
                self._unreachable_at[kind] = time.monotonic()
        else:
            self._unreachable_at.pop(kind, None)
        with WRITE_LOCK, self.sessions.begin() as s:
            row = s.scalar(select(AnchorRow).where(AnchorRow.record_id == record_id, AnchorRow.provider == kind))
            now = _now()
            row.attempts += 1
            row.updated_local = _iso(now)
            row.provider_name = (result.provider if result is not None and result.provider else provider.name)
            if result is not None and error is None:
                row.status = result.status
                row.proof_bytes = result.proof
                row.verified_time_utc = result.verified_time
                row.detail = result.detail
                row.last_error = None
                row.next_attempt_at = None if result.status == "confirmed" else _iso(now + timedelta(hours=1))
            else:
                row.last_error = error
                row.status = "failed" if row.attempts >= MAX_ATTEMPTS_BEFORE_FAILED else "pending"
                row.next_attempt_at = _iso(now + backoff_delay(row.attempts))

    # ------------------------------------------------------------------ refresh

    def ensure_rows(self) -> int:
        """Create missing anchor rows, e.g. after enabling the Bitcoin anchor later."""
        created = 0
        with WRITE_LOCK, self.sessions.begin() as s:
            ids = s.scalars(select(RecordRow.id)).all()
            existing = {(r.record_id, r.provider) for r in s.scalars(select(AnchorRow))}
            for rid in ids:
                for kind, provider in self.enabled().items():
                    if (rid, kind) not in existing:
                        s.add(
                            AnchorRow(
                                record_id=rid,
                                provider=kind,
                                provider_name=provider.name,
                                status="pending",
                                attempts=0,
                                detail="",
                                updated_local=_iso(_now()),
                            )
                        )
                        created += 1
        return created

    def refresh(self, force: bool = False) -> dict[str, int]:
        """Retry missing proofs and upgrade pending Bitcoin anchors.

        ``force`` ignores the backoff schedule (the manual "refresh" button).
        """
        self.ensure_rows()
        stats = {"submitted": 0, "upgraded": 0, "still_pending": 0, "errors": 0}
        now = _iso(_now())
        with self.sessions() as s:
            rows = [
                (r.record_id, r.provider, r.proof_bytes, r.status, r.next_attempt_at)
                for r in s.scalars(select(AnchorRow).where(AnchorRow.status != "confirmed"))
            ]
            manifests = {
                rid: s.get(RecordRow, rid).manifest_bytes for rid in {r[0] for r in rows}
            }
        with self._lock:
            for rid, kind, proof, _status, due in rows:
                provider = self.providers.get(kind)
                if provider is None:
                    continue
                if not force and due is not None and due > now:
                    continue
                if proof is None:
                    self._attempt(rid, kind, manifests[rid])
                    stats["submitted"] += 1
                    continue
                try:
                    result = provider.upgrade(proof)
                except Exception as exc:  # noqa: BLE001
                    stats["errors"] += 1
                    with WRITE_LOCK, self.sessions.begin() as s:
                        row = s.scalar(select(AnchorRow).where(AnchorRow.record_id == rid, AnchorRow.provider == kind))
                        row.attempts += 1
                        row.last_error = f"{type(exc).__name__}: {exc}"
                        row.next_attempt_at = _iso(_now() + backoff_delay(row.attempts))
                        row.updated_local = now
                    continue
                with WRITE_LOCK, self.sessions.begin() as s:
                    row = s.scalar(select(AnchorRow).where(AnchorRow.record_id == rid, AnchorRow.provider == kind))
                    row.proof_bytes = result.proof
                    row.updated_local = now
                    row.last_error = None
                    if result.status == "confirmed":
                        row.status = "confirmed"
                        row.verified_time_utc = result.verified_time
                        row.detail = result.detail
                        row.next_attempt_at = None
                        stats["upgraded"] += 1
                    else:
                        row.next_attempt_at = _iso(_now() + timedelta(hours=1))
                        stats["still_pending"] += 1
        return stats

    def rows_by_record(self) -> dict[str, dict[str, AnchorRow]]:
        with self.sessions() as s:
            out: dict[str, dict[str, AnchorRow]] = {}
            for row in s.scalars(select(AnchorRow)):
                out.setdefault(row.record_id, {})[row.provider] = row
            return out
