"""SQLite schema (PRD §8 "本地数据库").

``records`` is append-only: SQLite triggers abort any UPDATE or DELETE, and both
byte strings are stored exactly as signed — never re-serialized.
``anchors`` (time proofs) are not records and may change state.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# One writer at a time, process-wide (PRD §13 写入规则: "持有全局写锁").
# Every write transaction — records, anchors, metadata — runs under this lock, so
# SQLite never sees two competing writers; readers are never blocked (WAL).
WRITE_LOCK = threading.RLock()


class Base(DeclarativeBase):
    pass


class RecordRow(Base):
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    prev_id: Mapped[str | None] = mapped_column(String(64))
    manifest_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    payload_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[bytes] = mapped_column(LargeBinary)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_local: Mapped[str] = mapped_column(String(32))


class AnchorRow(Base):
    __tablename__ = "anchors"
    __table_args__ = (UniqueConstraint("record_id", "provider"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id"), index=True)
    provider: Mapped[str] = mapped_column(String(8))  # tsa | btc
    provider_name: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # pending | confirmed | failed
    proof_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    verified_time_utc: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[str | None] = mapped_column(String(32))
    updated_local: Mapped[str] = mapped_column(String(32))


class BlobRow(Base):
    __tablename__ = "blobs"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger)
    created_local: Mapped[str] = mapped_column(String(32))


class RecordFileRow(Base):
    __tablename__ = "record_files"
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(8), primary_key=True)  # body | file
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    sha256: Mapped[str] = mapped_column(ForeignKey("blobs.sha256"))
    size: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(127))


class ProjectRow(Base):
    """Local display names only; the name at recording time is fixed in each entry."""

    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    created_local: Mapped[str] = mapped_column(String(32))


class MetaRow(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


APPEND_ONLY_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
       BEGIN SELECT RAISE(ABORT, 'records are append-only: UPDATE is not allowed'); END""",
    """CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
       BEGIN SELECT RAISE(ABORT, 'records are append-only: DELETE is not allowed'); END""",
    """CREATE TRIGGER IF NOT EXISTS record_files_no_update BEFORE UPDATE ON record_files
       BEGIN SELECT RAISE(ABORT, 'record files are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS record_files_no_delete BEFORE DELETE ON record_files
       BEGIN SELECT RAISE(ABORT, 'record files are append-only'); END""",
)


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"timeout": 30, "check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - driver plumbing
        # Let SQLAlchemy, not pysqlite, decide when transactions begin.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=FULL")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):  # pragma: no cover - driver plumbing
        conn.exec_driver_sql("BEGIN")

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for ddl in APPEND_ONLY_TRIGGERS:
            conn.execute(text(ddl))


def make_sessionmaker(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)
