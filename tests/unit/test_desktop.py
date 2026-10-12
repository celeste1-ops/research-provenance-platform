"""The double-click launcher (D-044): one copy per data folder, port fallback, clean stop."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from app.desktop import InstanceLock, start_server, stop_server, tray_image
from tests.conftest import make_ctx


def test_only_one_copy_holds_the_lock(tmp_path):
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    assert first.acquire()
    first.publish(8771)
    assert not second.acquire()
    assert second.running_port(wait=0) == 8771
    first.release()
    assert second.acquire()  # released (the operating system also releases it if the app dies)
    second.release()


def test_the_lock_is_released_when_the_process_dies(tmp_path):
    holder = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(tmp_path.parent)!r})
        from app.desktop import InstanceLock
        lock = InstanceLock(__import__("pathlib").Path({str(tmp_path)!r}))
        assert lock.acquire()
        print("locked", flush=True)
        time.sleep(60)
    """)
    proc = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        assert proc.stdout.readline().strip() == "locked"
        assert not InstanceLock(tmp_path).acquire()
    finally:
        proc.kill()
        proc.wait()
    lock = InstanceLock(tmp_path)
    assert lock.acquire()
    lock.release()


def test_server_starts_on_the_next_free_port_and_stops(tmp_path):
    a = make_ctx(tmp_path / "a")
    b = make_ctx(tmp_path / "b")
    server_a, thread_a, port_a = start_server(a, 18765)
    try:
        server_b, thread_b, port_b = start_server(b, port_a)  # the first port is taken
        assert port_b == port_a + 1 and b.settings.port == port_b
        stop_server(server_b, thread_b, b)
        assert not thread_b.is_alive()
    finally:
        stop_server(server_a, thread_a, a)
    assert not thread_a.is_alive()


def test_tray_icon_is_drawn_without_files():
    img = tray_image(32)
    assert img.size == (32, 32) and img.getpixel((16, 2))[3] > 0


def test_make_run_refuses_while_another_copy_holds_the_data_folder(tmp_path, monkeypatch):
    """`make run` and the installed app take the same lock: never two servers on one data folder."""
    import uvicorn

    from app import main as app_main

    held = InstanceLock(tmp_path)
    assert held.acquire()
    held.publish(8799)
    monkeypatch.setenv("RPROV_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["app"])
    started = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k["port"]))
    monkeypatch.setattr(app_main, "app_factory", lambda: object())
    with pytest.raises(SystemExit) as exc:
        app_main.main()
    assert "already running" in str(exc.value.code) and "127.0.0.1:8799" in str(exc.value.code)
    assert started == []
    held.release()

    app_main.main()  # free again: it starts, and gives the lock back when the server stops
    assert len(started) == 1
    again = InstanceLock(tmp_path)
    assert again.acquire()
    again.release()


def test_menu_follows_the_language_chosen_in_the_app(tmp_path, monkeypatch):
    from app import desktop, preferences

    monkeypatch.setattr(desktop, "system_language", lambda: "en")
    assert desktop.menu_language(tmp_path) == "en"
    assert desktop.MENU["en"] == {"open": "Open Research History", "note": "Quick note…",
                                  "browser": "Open in browser", "quit": "Quit"}
    seen = []
    preferences.on_change(seen.append)
    try:
        preferences.save(tmp_path, language="zh")
    finally:
        preferences._listeners.remove(seen.append)
    assert seen == [{"language": "zh"}]
    assert desktop.menu_language(tmp_path) == "zh"
    assert desktop.MENU["zh"] == {"open": "打开 Research History", "note": "快速记一笔…",
                                  "browser": "在浏览器中打开", "quit": "退出"}


def test_system_language_is_read_from_the_environment(monkeypatch):
    from app import desktop

    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    assert desktop.system_language() == "zh"
    monkeypatch.setenv("LC_ALL", "en_GB.UTF-8")
    assert desktop.system_language() == "en"


def test_opening_the_app_again_shows_its_page(monkeypatch):
    """macOS re-activates a running app instead of starting a second one; the app answers by
    opening its page (before, nothing seemed to happen: the app has no window)."""
    from app import desktop

    opened = []
    monkeypatch.setattr(desktop, "open_browser", opened.append)
    desktop.reopened("http://127.0.0.1:8765/")
    assert opened == ["http://127.0.0.1:8765/"]
    if sys.platform != "darwin":
        desktop.watch_reopen("http://127.0.0.1:8765/")  # nothing to do elsewhere, and no error
        assert desktop._reopen_delegate == []


class FakePystray:
    """Just enough of pystray to read the menu the app builds."""

    class MenuItem:
        def __init__(self, text, action, default=False):
            self.text, self.action, self.default = text, action, default

    class Menu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class Icon:
        def __init__(self, name, image, title, menu):
            self.title, self.menu, self.stopped, self.notes = title, menu, False, []

        def stop(self):
            self.stopped = True

        def notify(self, text, title):
            self.notes.append((title, text))


class FakeShell:
    def __init__(self, has_window):
        self.has_window, self.url, self.calls, self.notify = has_window, "http://127.0.0.1:8765/", [], None

    def show(self, hash=""):
        self.calls.append(("show", hash))

    def open_in_browser(self):
        self.calls.append(("browser",))

    def quit(self):
        self.calls.append(("quit",))


def _menu(icon):
    return [i for i in icon.menu.items if i is not FakePystray.Menu.SEPARATOR]


def test_the_icon_opens_the_window_and_quit_quits(tmp_path, monkeypatch):
    from app import desktop, preferences

    monkeypatch.setitem(sys.modules, "pystray", FakePystray)
    monkeypatch.setattr(desktop, "system_language", lambda: "en")
    shell = FakeShell(has_window=True)
    icon = desktop.make_tray(shell, tmp_path)
    preferences._listeners.pop()  # the relabel hook this test added
    items = _menu(icon)
    assert [i.text(None) for i in items] == ["Open Research History", "Quick note…", "Open in browser", "Quit"]
    assert items[0].default
    for item in items:
        item.action(icon, item)
    assert shell.calls == [("show", ""), ("show", "#quick-note"), ("browser",), ("quit",)]
    assert not icon.stopped  # with a window, the window's event loop ends the app
    shell.notify("still running")
    assert icon.notes == [("Research History", "still running")]


def test_without_a_window_the_icon_works_as_before(tmp_path, monkeypatch):
    from app import desktop, preferences

    monkeypatch.setitem(sys.modules, "pystray", FakePystray)
    monkeypatch.setattr(desktop, "system_language", lambda: "zh")
    opened = []
    monkeypatch.setattr(desktop, "open_browser", opened.append)
    quits = []
    shell = desktop.BrowserShell("http://127.0.0.1:8765/", lambda: quits.append(1))
    icon = desktop.make_tray(shell, tmp_path)
    preferences._listeners.pop()
    items = _menu(icon)
    assert [i.text(None) for i in items] == ["打开 Research History", "快速记一笔…", "退出"]
    for item in items:
        item.action(icon, item)
    assert opened == ["http://127.0.0.1:8765/", "http://127.0.0.1:8765/#quick-note"]
    assert quits == [1] and icon.stopped
