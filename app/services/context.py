"""Wires settings → database, blob store, keystore, providers, services."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import init_db, make_engine, make_sessionmaker
from app.services.anchors import AnchorService
from app.services.blobs import BlobStore
from app.services.keystore import KeyStore, make_keystore
from app.services.ledger import Ledger
from provenance_core.providers.base import TimestampProvider


def public_tsa(settings: Settings, name: str) -> TimestampProvider:
    """One of the two built-in time-stamping authorities, each pinned to its own root (D-045)."""
    from provenance_core.certs import (
        BUILTIN_TSA_ROOTS,
        digicert_bundle_files,
        freetsa_bundle_files,
        load_pinned,
    )
    from provenance_core.providers.rfc3161 import Rfc3161Provider

    pinned = {file: load_pinned(file, sha) for file, _label, sha in BUILTIN_TSA_ROOTS}
    if name == "freetsa":
        return Rfc3161Provider(url=settings.tsa_url, timeout=settings.network_timeout, name="freetsa",
                               roots=[pinned["freetsa-cacert.pem"]], bundle_files=freetsa_bundle_files())
    if name == "digicert":
        return Rfc3161Provider(url=settings.digicert_tsa_url, timeout=settings.network_timeout, name="digicert",
                               roots=[pinned["digicert-trusted-root-g4.pem"]], bundle_files=digicert_bundle_files())
    raise ValueError(f"unknown time-stamping authority {name!r}")


def make_providers(settings: Settings) -> dict[str, TimestampProvider | None]:
    """The only place providers (and therefore network access) are constructed."""
    tsa: TimestampProvider | None
    if settings.tsa in ("freetsa", "digicert"):
        from provenance_core.providers.tsa_chain import TsaChain

        tsa = TsaChain([public_tsa(settings, name) for name in services_in_use(settings)["tsa"]])
    elif settings.tsa == "mock":
        from provenance_core.providers.mock import MockProvider

        tsa = MockProvider("tsa")
    elif settings.tsa == "off":
        tsa = None
    else:
        raise ValueError(f"unknown RPROV_TSA={settings.tsa!r}")
    btc: TimestampProvider | None
    if settings.btc == "ots":
        from provenance_core.providers.explorers import ExplorerHeaderLookup, NodeHeaderLookup
        from provenance_core.providers.ots import OtsProvider

        lookup = NodeHeaderLookup(settings.bitcoin_rpc) if settings.bitcoin_rpc else ExplorerHeaderLookup()
        btc = OtsProvider(timeout=settings.network_timeout, header_lookup=lookup)
    elif settings.btc == "mock":
        from provenance_core.providers.mock import MockProvider

        btc = MockProvider("btc")
    elif settings.btc == "off":
        btc = None
    else:
        raise ValueError(f"unknown RPROV_BTC={settings.btc!r}")
    return {"tsa": tsa, "btc": btc}


def check_stamp_services(settings: Settings) -> dict:
    """“Check stamp services” (D-045): can the built-in authorities, the OpenTimestamps
    calendars and the block explorers be reached from here? Only random values are sent."""
    from provenance_core.providers.diagnostics import run_checks

    tsas = [("FreeTSA", public_tsa(settings, "freetsa")), ("DigiCert", public_tsa(settings, "digicert"))]
    from app.i18n import tr_message

    checks = [c.to_dict() for c in run_checks(tsas, timeout=settings.network_timeout)]
    for c in checks:
        c["detail"] = tr_message(c["detail"])  # written in English by the checks (D-046)
    return {"checks": checks, "in_use": services_in_use(settings)}


def services_in_use(settings: Settings) -> dict:
    """What this app is set to use, so the check can say which results matter."""
    tsa: list[str] = []
    if settings.tsa in ("freetsa", "digicert"):
        tsa = [settings.tsa]
        fallback = settings.tsa_fallback or {"freetsa": "digicert", "digicert": "freetsa"}[settings.tsa]
        if fallback != "off" and fallback not in tsa:
            tsa.append(fallback)
    return {"tsa": tsa, "btc": settings.btc == "ots", "explorers": settings.btc == "ots" and not settings.bitcoin_rpc}


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
    autobackup: object = field(default=None, repr=False)
    # “Check stamp services”; tests swap it for one that makes no network requests.
    service_check: Callable[[], dict] | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        keystore: KeyStore | None = None,
        providers: dict[str, TimestampProvider | None] | None = None,
        backups: bool = True,
    ) -> AppContext:
        settings.ensure_data_dir()
        engine = make_engine(settings.db_path)
        init_db(engine)
        sessions = make_sessionmaker(engine)
        blobs = BlobStore(settings.blob_dir)
        keystore = keystore or make_keystore(settings.keystore, settings.data_dir)
        anchors = AnchorService(sessions, providers if providers is not None else make_providers(settings))
        ledger = Ledger(sessions, blobs, keystore, anchors)
        ctx = cls(settings, engine, sessions, blobs, keystore, anchors, ledger, secrets.token_urlsafe(32))
        ctx.service_check = lambda: check_stamp_services(settings)
        from app.services.autobackup import AutoBackup

        ctx.autobackup = AutoBackup(ctx)
        if backups:  # the practice space is never backed up
            ledger.listeners.append(ctx.autobackup.schedule)
            ctx.autobackup.detect_copied_folder()
        return ctx

    def close(self) -> None:
        if self.autobackup is not None:
            self.autobackup.stop()
        self.engine.dispose()
