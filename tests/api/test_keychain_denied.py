"""The keychain is asked as little as possible, and a refusal is never retried on its own.

An app that is not signed by a developer is asked about by macOS for each keychain item it did
not create itself, after every upgrade, unless the person chose "Always Allow". The page asks the
server for its status every few seconds; each answer used to read the backup password again, so
the question came back without end, and a refusal turned the status into an internal error.
"""

from __future__ import annotations

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.errors import KeyringLocked

from app.main import create_app
from app.services import backup as backup_mod
from app.services.keystore import KeychainDenied, KeyringKeyStore
from tests.conftest import make_ctx

PASSWORD = "backup password 1"
BASE = "http://127.0.0.1:8765"


class FakeKeychain(KeyringBackend):
    """Counts reads, and refuses them the way macOS does after "Deny"."""

    priority = 1

    def __init__(self):
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}
        self.reads = 0
        self.refuse = False

    def get_password(self, service, username):
        self.reads += 1
        if self.refuse:
            raise KeyringLocked("Can't get password from keychain: (-128, 'Keychain Access Denied')")
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        if self.refuse:
            raise KeyringLocked("Can't store password on keychain: (-128, 'Keychain Access Denied')")
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self.items.pop((service, username), None)


@pytest.fixture
def chain():
    previous = keyring.get_keyring()
    fake = FakeKeychain()
    keyring.set_keyring(fake)
    KeyringKeyStore().retry()  # every test starts with the gate open
    yield fake
    KeyringKeyStore().retry()
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(backup_mod, "SCRYPT_N", 2**14)


def _set_up(tmp_path) -> str:
    """An identity with automatic backup, as the previous version of the app left it."""
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())
    ctx.ledger.init_identity("R")
    pid = ctx.ledger.create_project("P").id
    ctx.autobackup.configure(str(tmp_path / "bk"), PASSWORD, create=True)
    ctx.close()
    return pid


def _client(ctx) -> TestClient:
    cl = TestClient(create_app(ctx), base_url=BASE)
    cl.headers["X-RPROV-Token"] = ctx.session_token
    return cl


def test_the_gate_stops_asking_after_a_refusal(chain):
    store, other = KeyringKeyStore(), KeyringKeyStore()
    chain.refuse = True
    with pytest.raises(KeychainDenied):
        store.load_secret("x")
    assert chain.reads == 1 and store.denied and other.denied  # one gate for the whole app
    for call in (lambda: store.load_secret("x"), lambda: other.load("inst"), lambda: store.save_secret("x", "y")):
        with pytest.raises(KeychainDenied):
            call()
    assert chain.reads == 1  # nothing reached the keychain, so nothing asked the person
    chain.refuse = False
    store.retry()
    assert store.load_secret("x") is None and chain.reads == 2 and not other.denied


def test_the_status_reads_the_backup_password_once(tmp_path, chain):
    _set_up(tmp_path)
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())  # the app starts again
    before = chain.reads
    with _client(ctx) as cl:
        for _ in range(10):
            st = cl.get("/api/status").json()
            assert st["backup"]["configured"] and st["backup"]["key_fingerprint"] and not st["keychain_denied"]
    assert chain.reads == before + 1  # once, then remembered; the signing key is not read for this
    assert ctx.autobackup.run("test")["ran"]  # the backup itself reads only the signing key
    assert chain.reads == before + 2
    ctx.close()


def test_a_refusal_waits_for_try_again(tmp_path, chain):
    pid = _set_up(tmp_path)
    chain.refuse = True
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())
    ctx.autobackup.debounce = 0
    with _client(ctx) as cl:
        r = cl.get("/api/status")
        assert r.status_code == 200  # no longer an internal error
        st = r.json()
        assert st["keychain_denied"] and st["backup"]["state"] == "keychain-denied"
        assert st["backup"]["keychain_denied"] and not st["backup"].get("needs_password")
        reads = chain.reads
        for _ in range(10):
            assert cl.get("/api/status").status_code == 200
        assert chain.reads == reads  # the page keeps asking the server; the server does not ask the person

        # Saving a step needs the signing key: a clear refusal the page can show, not an internal error.
        r = cl.post("/api/entries", data={"project_id": pid, "node_type": "idea", "title": "first"})
        assert r.status_code == 403 and r.json()["keychain_denied"] and "Try again" in r.json()["detail"]
        assert ctx.autobackup.run("test") == {"ran": False, "reason": r.json()["detail"]}
        assert not ctx.ledger.meta("backup_last_error")  # waiting is not a failed backup
        assert chain.reads == reads

        # Try again, and this time the person allows it: both questions come now, then never again.
        chain.refuse = False
        assert cl.post("/api/keychain/retry").json() == {"keychain_denied": False}
        assert chain.reads == reads + 2
        st = cl.get("/api/status").json()
        assert not st["keychain_denied"] and st["backup"]["state"] != "keychain-denied" and st["backup"]["configured"]
        assert cl.post("/api/entries", data={"project_id": pid, "node_type": "idea", "title": "first"}).status_code == 200
        assert chain.reads == reads + 2
    ctx.close()


def test_try_again_and_refused_again(tmp_path, chain):
    _set_up(tmp_path)
    chain.refuse = True
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())
    with _client(ctx) as cl:
        cl.get("/api/status")
        assert cl.post("/api/keychain/retry").json() == {"keychain_denied": True}
        assert cl.get("/api/status").json()["keychain_denied"]
    ctx.close()


def test_the_refusal_message_is_translated(tmp_path, chain):
    pid = _set_up(tmp_path)
    chain.refuse = True
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())
    with _client(ctx) as cl:
        cl.headers["X-RPROV-Lang"] = "zh"
        r = cl.post("/api/entries", data={"project_id": pid, "node_type": "idea", "title": "first"})
        assert r.status_code == 403 and "始终允许" in r.json()["detail"]
    ctx.close()
