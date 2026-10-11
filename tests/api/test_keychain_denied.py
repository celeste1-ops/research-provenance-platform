"""The keychain is asked as little as possible, and a refusal is never retried on its own.

An app that is not signed by a developer is asked about by macOS for each keychain item it did
not create itself, after every upgrade, unless the person chose "Always Allow". The page asks the
server for its status every few seconds; each answer used to read the backup password again, so
the question came back without end, and a refusal turned the status into an internal error.
"""

from __future__ import annotations

import json

import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.errors import KeyringLocked

from app.main import create_app
from app.services import backup as backup_mod
from app.services.keystore import KeychainDenied, KeyringKeyStore, KeyStoreError
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
def chain(monkeypatch):
    monkeypatch.setattr(KeyringKeyStore, "one_item", True)  # as on macOS, wherever the tests run
    previous = keyring.get_keyring()
    fake = FakeKeychain()
    keyring.set_keyring(fake)
    KeyringKeyStore().retry()  # every test starts with the gate open and nothing read yet
    KeyringKeyStore.forget()
    yield fake
    KeyringKeyStore().retry()
    KeyringKeyStore.forget()
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
    KeyringKeyStore.forget()  # what follows is a new run of the app
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
    assert store.load_secret("x") is None and not other.denied
    assert chain.reads == 3  # the app's one item, then the item an older version would have used


def test_the_status_reads_the_backup_password_once(tmp_path, chain):
    _set_up(tmp_path)
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())  # the app starts again
    before = chain.reads
    with _client(ctx) as cl:
        for _ in range(10):
            st = cl.get("/api/status").json()
            assert st["backup"]["configured"] and st["backup"]["key_fingerprint"] and not st["keychain_denied"]
    assert chain.reads == before + 1  # once, then remembered; the signing key is not read for this
    assert ctx.autobackup.run("test")["ran"]  # the signing key is in the same keychain item: no new question
    assert chain.reads == before + 1
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

        # Try again, and this time the person allows it: one question now (password and key are
        # in one keychain item), then never again.
        chain.refuse = False
        assert cl.post("/api/keychain/retry").json() == {"keychain_denied": False}
        assert chain.reads == reads + 1
        st = cl.get("/api/status").json()
        assert not st["keychain_denied"] and st["backup"]["state"] != "keychain-denied" and st["backup"]["configured"]
        assert cl.post("/api/entries", data={"project_id": pid, "node_type": "idea", "title": "first"}).status_code == 200
        assert chain.reads == reads + 1
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


def test_items_of_older_versions_move_into_one(tmp_path, chain):
    """Up to 0.3.1 every key and secret had a keychain item of its own, so each upgrade asked once
    per item. They move into the app's one item the first time each is needed; after that a new
    version asks once."""
    _set_up(tmp_path)
    bundle = json.loads(chain.items.pop(("rprov", "secrets")))
    for inst, key in bundle["keys"].items():
        chain.items[("rprov-signing-key", inst)] = key
    for name, value in bundle["secrets"].items():
        chain.items[("rprov-secret", name)] = value
    old_items = dict(chain.items)

    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())
    with _client(ctx) as cl:
        assert cl.get("/api/status").json()["backup"]["configured"]
    assert ctx.autobackup.run("test")["ran"]
    ctx.close()
    moved = json.loads(chain.items[("rprov", "secrets")])
    assert moved == bundle  # the same key and password, now in one item
    assert all(chain.items[k] == v for k, v in old_items.items())  # the old items are left alone

    KeyringKeyStore.forget()  # the next version
    before = chain.reads
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())
    with _client(ctx) as cl:
        assert cl.get("/api/status").json()["backup"]["configured"]
    assert ctx.autobackup.run("test")["ran"]
    assert chain.reads == before + 1
    ctx.close()


def test_an_unreadable_item_is_never_overwritten(chain):
    chain.items[("rprov", "secrets")] = "not json"
    store = KeyringKeyStore()
    with pytest.raises(KeyStoreError):
        store.save_secret("x", "y")
    assert chain.items[("rprov", "secrets")] == "not json"


def test_elsewhere_every_secret_keeps_its_own_item(tmp_path, chain, monkeypatch):
    """Windows Credential Manager asks nothing and limits the size of an item."""
    monkeypatch.setattr(KeyringKeyStore, "one_item", False)
    _set_up(tmp_path)
    assert ("rprov", "secrets") not in chain.items
    assert {service for service, _ in chain.items} == {"rprov-signing-key", "rprov-secret"}
    ctx = make_ctx(tmp_path, keystore=KeyringKeyStore())
    with _client(ctx) as cl:
        assert cl.get("/api/status").json()["backup"]["configured"]
    ctx.close()
