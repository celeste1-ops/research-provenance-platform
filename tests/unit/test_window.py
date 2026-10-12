"""The app's own window (D-058): closing hides it, the icon and a second start show it, Quit
quits; and how it starts, set up through a stand-in for pywebview (no real window here)."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time

import pytest

from app import desktop
from app import window as app_window
from app.instance import InstanceLock
from app.window import AppWindow


class FakeEvent:
    """Like pywebview's Event: handlers run in order; any False return cancels."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def set(self, *args):
        return any(h(*args) is False for h in list(self.handlers))


class FakeEvents:
    def __init__(self):
        for name in ("closing", "loaded", "minimized", "restored", "resized", "before_show", "closed"):
            setattr(self, name, FakeEvent())


class FakeWindow:
    def __init__(self, **options):
        self.options = options
        self.events = FakeEvents()
        self.calls = []
        self.visible = True
        self.closed = threading.Event()
        self.scripts = []

    def show(self):
        self.calls.append("show")
        self.visible = True

    def hide(self):
        self.calls.append("hide")
        self.visible = False

    def restore(self):
        self.calls.append("restore")

    def destroy(self):
        # Like a real window: asks "closing" first, and only closes if nothing said no.
        self.calls.append("destroy")
        if not self.events.closing.set():
            self.closed.set()

    def evaluate_js(self, script):
        self.scripts.append(script)
        return True

    def user_closes(self):
        """The red button / the × of the window."""
        if not self.events.closing.set():
            self.closed.set()


class FakeWebview:
    def __init__(self):
        self.settings = {"ALLOW_DOWNLOADS": False, "OPEN_EXTERNAL_LINKS_IN_BROWSER": False}
        self.window = None
        self.started = {}

    def create_window(self, title, url, **options):
        self.window = FakeWindow(title=title, url=url, **options)
        return self.window

    def start(self, func, **options):
        """The event loop: the page loads, ``func`` runs in a thread, and the loop runs until the
        window is closed for good."""
        self.started = options
        self.window.events.loaded.set()
        threading.Thread(target=func, daemon=True).start()
        assert self.window.closed.wait(30), "the window was never closed"


def make(tmp_path, platform="linux", lang="en", **kw):
    quits = []
    wv = FakeWebview()
    shell = AppWindow("http://127.0.0.1:8765/", tmp_path, lambda: quits.append(1), language=lambda: lang,
                      webview=wv, platform=platform, **kw)
    return shell, wv, quits


def wait_for(cond, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_the_window_shows_the_local_page_and_lets_you_copy_text_and_download(tmp_path):
    shell, wv, _ = make(tmp_path)
    window = shell.create()
    assert window.options["url"] == "http://127.0.0.1:8765/" and window.options["title"] == "Research History"
    assert window.options["text_select"] is True  # pywebview's default would stop copying text
    assert window.options["min_size"] == app_window.MIN_SIZE
    assert (window.options["width"], window.options["height"]) == app_window.SIZE
    assert wv.settings["ALLOW_DOWNLOADS"] is True  # evidence bundles, key backups, attachments ask where to save
    assert wv.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True  # DOI and GitHub links open in the browser


def test_closing_the_window_hides_it_and_says_so_once(tmp_path, monkeypatch):
    shell, _, quits = make(tmp_path, platform="darwin", lang="zh")
    told = []
    shell.notify = told.append
    monkeypatch.setattr(app_window, "_mac_dock", lambda visible: None)
    window = _create_without_native_hooks(shell)

    window.user_closes()
    assert not window.closed.is_set() and shell.hidden and window.calls == ["hide"]
    assert quits == []  # the server and background jobs keep running
    assert wait_for(lambda: told)
    assert told == [app_window.HIDDEN["zh"]["darwin"]] and "菜单栏" in told[0]
    assert json.loads((tmp_path / app_window.STATE_FILE).read_text())["told_hidden"] is True

    shell.show()
    window.user_closes()  # the second time: hidden again, without the message
    time.sleep(0.1)
    assert told == [app_window.HIDDEN["zh"]["darwin"]]


def _create_without_native_hooks(shell):
    """create() for a macOS / Windows window, without pywebview's real platform code."""
    real = app_window._mac_install
    app_window._mac_install = lambda _shell: None
    try:
        return shell.create()
    finally:
        app_window._mac_install = real


def test_the_icon_and_a_second_start_show_the_one_window(tmp_path):
    shell, _, _ = make(tmp_path)
    window = shell.create()
    window.user_closes()
    shell.show()
    assert window.visible and not shell.hidden and window.calls == ["hide", "show"]

    window.events.minimized.set()
    shell.show("#quick-note")  # "Quick note…" in the icon's menu
    assert window.calls[-2:] == ["restore", "show"]
    assert wait_for(lambda: window.scripts)
    assert window.scripts == ['window.location.hash = "#quick-note"']


def test_quit_closes_the_window_for_good_and_stops_the_app(tmp_path):
    shell, _, quits = make(tmp_path, platform="win32")
    window = shell.create()
    shell.quit()
    assert shell.quitting and window.closed.is_set() and window.calls == ["destroy"]
    shell.show()  # too late: nothing happens
    assert window.calls == ["destroy"]
    assert quits == []  # desktop.main stops the server when the event loop has ended


def test_windows_tells_a_close_by_you_from_shutting_down(tmp_path):
    shell, _, _ = make(tmp_path, platform="win32")
    window = shell.create()
    shell._form_decides = True  # the form's own handler is watching (app.window._windows_watch_close)
    assert window.events.closing.set() is True  # pywebview's handler: keep it for now
    assert shell.form_closing("UserClosing", user=True) is False  # you: hide
    assert shell.hidden and not shell.quitting
    assert shell.form_closing("WindowsShutDown", user=False) is True  # Windows: let it close
    assert shell.quitting


def test_macos_quit_stops_the_server_before_the_app_ends(tmp_path, monkeypatch):
    shell, _, quits = make(tmp_path, platform="darwin")
    monkeypatch.setattr(app_window, "_mac_dock", lambda visible: None)
    window = _create_without_native_hooks(shell)
    replies = []
    assert shell.terminating(replies.append) == 2  # NSTerminateLater: answer when the server has stopped
    assert shell.quitting and window.calls == ["hide"]
    assert wait_for(lambda: replies)
    assert quits == [1] and replies == [True]
    window.user_closes()  # closing now really closes
    assert window.closed.is_set()


def test_macos_has_a_dock_icon_only_while_the_window_is_open(tmp_path, monkeypatch):
    shell, _, _ = make(tmp_path, platform="darwin")
    dock = []
    monkeypatch.setattr(app_window, "_mac_dock", dock.append)
    terminate = []
    monkeypatch.setattr(app_window, "_mac_terminate", lambda: terminate.append(1))
    window = _create_without_native_hooks(shell)
    window.user_closes()
    shell.show()
    assert dock == [False, True]
    shell.quit()  # goes through macOS's own quit, like ⌘Q
    assert terminate == [1] and not window.closed.is_set()


def test_the_window_keeps_its_size(tmp_path):
    shell, _, _ = make(tmp_path)
    window = shell.create()
    window.events.resized.set(1400, 900)
    window.events.minimized.set()
    window.events.resized.set(0, 0)  # minimized: not a size to keep
    window.user_closes()
    state = json.loads((tmp_path / app_window.STATE_FILE).read_text())
    assert (state["width"], state["height"]) == (1400, 900)

    again, _, _ = make(tmp_path)
    assert (again.create().options["width"], again.window.options["height"]) == (1400, 900)

    (tmp_path / app_window.STATE_FILE).write_text('{"width": 99999, "height": "x"}')
    odd, _, _ = make(tmp_path)
    assert (odd.create().options["width"], odd.window.options["height"]) == app_window.SIZE


def test_the_window_starts_with_lasting_storage_and_the_menus_in_your_language(tmp_path):
    shell, wv, _ = make(tmp_path, lang="zh")
    window = shell.create()
    ran = []
    threading.Timer(0.2, window.user_closes).start()
    threading.Timer(0.3, shell.quit).start()
    shell.run(lambda: ran.append(1))
    assert ran == [1] and shell.loaded.is_set()
    assert wv.started["private_mode"] is False  # the page's own settings (view, tips) are kept
    assert wv.started["localization"]["cocoa.menu.copy"] == "拷贝"


def test_a_page_that_never_loads_opens_in_the_browser_too(tmp_path, monkeypatch):
    shell, wv, _ = make(tmp_path)
    opened = []
    monkeypatch.setattr(app_window, "_open_browser", opened.append)
    monkeypatch.setattr(app_window, "LOAD_TIMEOUT", 0.1)
    window = shell.create()
    wv.start = lambda func, **kw: (func(), window.closed.set())
    shell.run()
    assert opened == ["http://127.0.0.1:8765/"]


def test_no_window_on_linux_so_the_browser_is_used():
    if sys.platform in ("darwin", "win32"):
        pytest.skip("this system has a window")
    assert "macOS and Windows" in app_window.engine_problem()


# ---------------------------------------------------------------- a second start


def test_a_second_start_asks_the_running_copy_to_show_its_window(tmp_path):
    first = InstanceLock(tmp_path)
    assert first.acquire()
    (tmp_path / "app.show").write_text("left over")  # from a start that gave up: not a request
    shown, stop = [], threading.Event()
    watcher = threading.Thread(target=first.watch_show_requests, args=(lambda: shown.append(1), stop, 0.02))
    watcher.start()
    try:
        time.sleep(0.1)
        assert shown == []
        assert InstanceLock(tmp_path).ask_to_show(wait=5)
        assert wait_for(lambda: shown == [1])
    finally:
        stop.set()
        watcher.join()
        first.release()


def test_a_copy_that_does_not_answer_gets_the_browser(tmp_path):
    held = InstanceLock(tmp_path)
    assert held.acquire()  # e.g. `make run`, which shows no window
    try:
        assert not InstanceLock(tmp_path).ask_to_show(wait=0.2)
        assert not (tmp_path / "app.show").exists()
    finally:
        held.release()


def test_starting_the_app_again_shows_the_window_instead_of_the_browser(tmp_path, monkeypatch):
    held = InstanceLock(tmp_path)
    assert held.acquire()
    held.publish(8799)
    monkeypatch.setenv("RPROV_HOME", str(tmp_path))
    opened = []
    monkeypatch.setattr(desktop, "open_browser", opened.append)
    monkeypatch.setattr(desktop, "setup_logging", lambda data_dir: data_dir / "app.log")
    shown, stop = [], threading.Event()
    watcher = threading.Thread(target=held.watch_show_requests, args=(lambda: shown.append(1), stop, 0.02))
    watcher.start()
    try:
        assert desktop.main([]) == 0
        assert shown == [1] and opened == []
    finally:
        stop.set()
        watcher.join()
    assert desktop.main([]) == 0  # nobody answers now (an older version, or `make run`)
    assert opened == ["http://127.0.0.1:8799/"]
    held.release()


# ---------------------------------------------------------------- the whole app, with a stand-in window


def test_the_app_runs_in_its_window_and_passes_the_window_check(tmp_path, monkeypatch, caplog):
    """desktop.main with --check-window, as the packaging smoke test runs it on macOS and Windows:
    the page is drawn, closing hides the window while the server keeps running, a second start
    shows it, Quit stops the server and frees the data folder."""
    monkeypatch.setenv("RPROV_HOME", str(tmp_path))
    monkeypatch.setenv("RPROV_KEYSTORE", "memory")
    monkeypatch.setenv("RPROV_TSA", "off")
    monkeypatch.setenv("RPROV_BTC", "off")
    monkeypatch.setattr(desktop, "setup_logging", lambda data_dir: data_dir / "app.log")
    monkeypatch.setattr(desktop, "make_tray", lambda shell, data_dir: None)
    monkeypatch.setattr(app_window, "engine_problem", lambda: None)
    shells = []

    def fake_window(*args, **kwargs):
        shell = AppWindow(*args, webview=FakeWebview(), platform="linux", **kwargs)
        shells.append(shell)
        return shell

    monkeypatch.setattr(app_window, "AppWindow", fake_window)

    def failed(code):  # check_window ends the process on failure; here, end only its thread
        raise SystemExit(code)

    monkeypatch.setattr(desktop.os, "_exit", failed)
    if sys.platform == "darwin":
        monkeypatch.setattr(app_window, "mac_simulate_close", lambda w: w.user_closes())
    with caplog.at_level(logging.INFO, logger="rprov.desktop"):
        assert desktop.main(["--check-window", "--port", "18791"]) == 0
    assert "window check passed" in caplog.text
    window = shells[0].window
    assert window.calls == ["destroy", "hide", "show", "destroy"]  # closed by "you": hidden; shown again; quit
    assert window.closed.is_set() and shells[0].quitting
    lock = InstanceLock(tmp_path)
    assert lock.acquire()  # given back
    lock.release()


def test_the_real_pywebview_takes_these_options(tmp_path):
    """The stand-in above mirrors pywebview; this checks the real one accepts the same settings,
    window options and events (it makes the window object only: no window opens here)."""
    webview = pytest.importorskip("webview")
    saved = dict(webview.settings)
    shell = AppWindow("http://127.0.0.1:8765/", tmp_path, lambda: None, language=lambda: "en",
                      webview=webview, platform="linux")
    try:
        window = shell.create()
        assert window.original_url == "http://127.0.0.1:8765/" and window.text_select is True
        assert webview.settings["ALLOW_DOWNLOADS"] is True
        from webview.localization import original_localization

        assert set(app_window.LOCALIZATION["zh"]) <= set(original_localization)
        for name in ("closing", "loaded", "minimized", "restored", "resized", "before_show"):
            assert len(getattr(window.events, name)) >= (0 if name == "before_show" else 1)
    finally:
        if shell.window in webview.windows:
            webview.windows.remove(shell.window)
        for key, value in saved.items():
            webview.settings[key] = value


def test_a_window_that_cannot_be_made_leaves_the_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("RPROV_HOME", str(tmp_path))
    monkeypatch.setenv("RPROV_KEYSTORE", "memory")
    monkeypatch.setenv("RPROV_TSA", "off")
    monkeypatch.setenv("RPROV_BTC", "off")
    monkeypatch.setattr(desktop, "setup_logging", lambda data_dir: data_dir / "app.log")
    monkeypatch.setattr(app_window, "engine_problem", lambda: None)

    class Broken(AppWindow):
        def create(self):
            raise RuntimeError("no window today")

    monkeypatch.setattr(app_window, "AppWindow", lambda *a, **k: Broken(*a, webview=FakeWebview(), **k))
    used = []
    monkeypatch.setattr(desktop, "run_browser", lambda shell, data_dir, args, thread: used.append(shell))
    assert desktop.main(["--port", "18793"]) == 0
    assert len(used) == 1 and isinstance(used[0], desktop.BrowserShell)
