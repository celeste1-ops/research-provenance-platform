"""After the keychain refused access, the top of the page says so and offers Try again."""

from __future__ import annotations

import pytest

from app.services.keystore import KeyringKeyStore
from tests.api.test_keychain_denied import _set_up, chain, fast_kdf  # noqa: F401  (fixtures)
from tests.e2e.server import LiveServer

pytestmark = pytest.mark.e2e
expect = pytest.importorskip("playwright.sync_api").expect


def test_banner_and_try_again(tmp_path, browser, chain):  # noqa: F811
    _set_up(tmp_path)
    chain.refuse = True  # the person clicked Deny
    with LiveServer(tmp_path, keystore=KeyringKeyStore()) as srv:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        banner = page.get_by_test_id("keychain-denied")
        expect(banner).to_contain_text("Keychain refused access")
        expect(page.get_by_test_id("backup-pill")).to_contain_text("Backup waits for the Keychain")
        reads = chain.reads
        page.reload()
        expect(banner).to_be_visible()
        assert chain.reads == reads  # reloading the page does not ask again

        chain.refuse = False  # this time the person chooses Always Allow
        page.get_by_test_id("keychain-retry").click()
        expect(page.get_by_test_id("notice")).to_contain_text("gave access again")
        expect(banner).to_have_count(0)
        expect(page.get_by_test_id("backup-pill")).not_to_contain_text("waits")
        page.close()


def test_a_refused_save_shows_the_banner_at_once(tmp_path, browser, chain):  # noqa: F811
    _set_up(tmp_path)
    with LiveServer(tmp_path, keystore=KeyringKeyStore()) as srv:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(srv.url)
        page.get_by_test_id("backup-pill").wait_for()
        expect(page.get_by_test_id("keychain-denied")).to_have_count(0)
        chain.refuse = True  # the signing key has not been read yet; the person will click Deny
        srv.ctx.ledger._key = None
        page.get_by_test_id("quick-note-open").click()
        page.get_by_test_id("quick-note-text").fill("A thought")
        page.get_by_test_id("quick-note-save").click()
        expect(page.get_by_test_id("quick-note")).to_contain_text("Try again")  # the box says why
        expect(page.get_by_test_id("keychain-denied")).to_be_visible()  # and the banner is there already
        page.close()
