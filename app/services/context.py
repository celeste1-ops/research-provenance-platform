"""Wires settings → database, blob store, keystore, providers, services."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import init_db, make_engine, make_sessionmaker
from app.services.anchors import AnchorService
from app.services.blobs import BlobStore
from app.services.keystore import KeyStore, make_keystore
from app.services.ledger import Ledger
from provenance_core.providers.base import TimestampProvider


def make_providers(settings: Settings) -> dict[str, TimestampProvider | None]:
    """The only place providers (and therefore network access) are constructed."""
    tsa: TimestampProvider | None
    if settings.tsa == "freetsa":
        from provenance_core.providers.rfc3161 import Rfc3161Provider

        tsa = Rfc3161Provider(url=settings.tsa_url, timeout=settings.network_timeout)
    elif settings.tsa == "mock":
        from provenance_core.providers.mock import MockProvider

        tsa = MockProvider("tsa")
    elif settings.tsa == "off":
        tsa = None
    else:
        raise ValueError(f"unknown RPROV_TSA={settings.tsa!r}")
    btc: TimestampProvider | None
    if settings.btc == "ots":
        from provenance_core.providers.ots import OtsProvider

        btc = OtsProvider(timeout=settings.network_timeout)
    elif settings.btc == "mock":
        from provenance_core.providers.mock import MockProvider

        btc = MockProvider("btc")
    elif settings.btc == "off":
        btc = None
    else:
        raise ValueError(f"unknown RPROV_BTC={settings.btc!r}")
    return {"tsa": tsa, "btc": btc}


@dataclass
class AppContext:
    settings: Settings
    engine: Engine
    sessions: sessionmaker
    blobs: BlobStore
    keystore: KeyStore
    anchors: AnchorService
    ledger: Ledger
    session_token: str

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        keystore: KeyStore | None = None,
        providers: dict[str, TimestampProvider | None] | None = None,
    ) -> AppContext:
        settings.ensure_data_dir()
        engine = make_engine(settings.db_path)
        init_db(engine)
        sessions = make_sessionmaker(engine)
        blobs = BlobStore(settings.blob_dir)
        keystore = keystore or make_keystore(settings.keystore, settings.data_dir)
        anchors = AnchorService(sessions, providers if providers is not None else make_providers(settings))
        ledger = Ledger(sessions, blobs, keystore, anchors)
        return cls(settings, engine, sessions, blobs, keystore, anchors, ledger, secrets.token_urlsafe(32))

    def close(self) -> None:
        self.engine.dispose()
