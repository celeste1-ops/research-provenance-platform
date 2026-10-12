"""The app's own window (DECISIONS D-058).

The window shows the same page a browser would (``http://127.0.0.1:<port>/``), drawn by the
system's own web engine through pywebview: WKWebView on macOS, Microsoft Edge WebView2 on
Windows. The server, the core library and verify.py do not change, and no browser engine is
shipped with the app.

* Closing the window only hides it. The server and the background jobs (stamps, backups,
  watched folders, git) keep running, and the menu bar / tray icon stays; the first time, the
  icon says so.
* "Open", "Quick note…", starting the app again and (macOS) its Dock icon all show this one
  window.
* "Quit" in the icon's menu quits for real, and so do ⌘Q, signing out and shutting down.
* Where there is no engine (pywebview missing, Windows without WebView2, Linux during
  development) the app opens the browser as before; see ``engine_problem``.

No network code here either: the window is pointed at the address the server already serves.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

APP_NAME = "Research History"
SIZE = (1280, 860)
MIN_SIZE = (960, 640)
MAX_SIZE = 5000  # a remembered size larger than this is a mistake, not a screen
STATE_FILE = "window.json"  # <data folder>/window.json: the window's size, and what it has told you
LOAD_TIMEOUT = 45.0  # seconds; a page that never loads is opened in the browser as well
BACKGROUND = "#F5F6F8"  # the page's own background (web/src/styles.css --bg): no white flash

log = logging.getLogger("rprov.window")

# What the icon says the first time the window is closed.
HIDDEN = {
    "en": {
        "darwin": f"{APP_NAME} is still running in the menu bar at the top of the screen. "
                  "Click its icon there to open it again, or to quit.",
        "win32": f"{APP_NAME} is still running in the notification area, next to the clock. "
                 "Click its icon there to open it again, or to quit.",
    },
    "zh": {
        "darwin": f"{APP_NAME} 还在屏幕顶部的菜单栏里运行。点那里的图标可以再打开，或者退出。",
        "win32": f"{APP_NAME} 还在右下角时钟旁边的通知区域里运行。点那里的图标可以再打开，或者退出。",
    },
}

# The words pywebview puts in the macOS menus and the save dialog (its defaults are English).
LOCALIZATION = {
    "zh": {
        "global.quitConfirmation": "确定要退出吗？",
        "global.ok": "好",
        "global.quit": "退出",
        "global.cancel": "取消",
        "global.saveFile": "保存文件",
        "cocoa.menu.about": "关于",
        "cocoa.menu.services": "服务",
        "cocoa.menu.view": "显示",
        "cocoa.menu.edit": "编辑",
        "cocoa.menu.hide": "隐藏",
        "cocoa.menu.hideOthers": "隐藏其他",
        "cocoa.menu.showAll": "全部显示",
        "cocoa.menu.quit": "退出",
        "cocoa.menu.fullscreen": "进入全屏幕",
        "cocoa.menu.cut": "剪切",
        "cocoa.menu.copy": "拷贝",
        "cocoa.menu.paste": "粘贴",
        "cocoa.menu.selectAll": "全选",
        "windows.fileFilter.allFiles": "所有文件",
        "windows.fileFilter.otherFiles": "其他文件类型",
    },
}


def engine_problem() -> str | None:
    """Why no app window can be shown on this computer, or None when it can."""
    if sys.platform not in ("darwin", "win32"):
        return "the app window is made for macOS and Windows"
    try:
        import webview  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return f"pywebview is not available ({exc})"
    if sys.platform == "win32":
        try:
            # Loads .NET and looks for the WebView2 runtime the way pywebview itself will.
            from webview.platforms import winforms
        except Exception as exc:  # noqa: BLE001
            return f"the Windows window toolkit could not be loaded ({exc})"
        if not winforms.is_chromium:
            # pywebview would fall back to Internet Explorer's engine, which cannot run the page.
            return "Microsoft Edge WebView2 Runtime is not installed"
    return None


def storage_dir() -> str | None:
    """Where the window keeps the page's own settings (view, tips, language of this window).
    macOS keeps them in the app's WebKit folder by itself; on Windows, next to the program,
    away from the data folder and its backups."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return str(Path(base) / APP_NAME / "WebView2")
    return None


def load_state(data_dir: Path) -> dict:
    try:
        data = json.loads((data_dir / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(data_dir: Path, state: dict) -> None:
    try:
        tmp = data_dir / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, data_dir / STATE_FILE)
    except OSError:
        log.exception("could not save the window's size")


def remembered_size(state: dict) -> tuple[int, int]:
    try:
        w, h = int(state["width"]), int(state["height"])
    except (KeyError, TypeError, ValueError):
        return SIZE
    if MIN_SIZE[0] <= w <= MAX_SIZE and MIN_SIZE[1] <= h <= MAX_SIZE:
        return w, h
    return SIZE


class AppWindow:
    """One window for the life of the app: shown and hidden, closed only to quit."""

    def __init__(self, url: str, data_dir: Path, on_quit: Callable[[], None], *,
                 language: Callable[[], str], webview=None, platform: str = sys.platform):
        self.url = url
        self.data_dir = data_dir
        self._on_quit = on_quit
        self._language = language
        self._webview = webview  # the pywebview module (a stand-in in tests)
        self._platform = platform
        self.window = None
        self.has_window = True
        self.quitting = False
        self.hidden = False
        self.loaded = threading.Event()
        self.notify: Callable[[str], None] | None = None  # set with the icon: a short message by it
        self._minimized = False
        self._state = load_state(data_dir)
        self._size = remembered_size(self._state)
        self._form_decides = False  # Windows: the form's own handler decides what a close means

    # ------------------------------------------------------------ setting up

    def create(self):
        wv = self._webview
        if wv is None:
            import webview as wv

            self._webview = wv
        wv.settings["ALLOW_DOWNLOADS"] = True  # a download asks where to save it
        wv.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # DOI, GitHub, … open in the browser
        width, height = self._size
        self.window = wv.create_window(
            APP_NAME, self.url, width=width, height=height, min_size=MIN_SIZE,
            text_select=True,  # pywebview's default stops copying text out of the page
            zoomable=True, background_color=BACKGROUND,
        )
        events = self.window.events
        events.closing += self._closing
        events.loaded += self._loaded
        events.minimized += self._on_minimized
        events.restored += self._on_restored
        events.resized += self._on_resized
        if self._platform == "win32":
            events.before_show += self._before_show_windows
        elif self._platform == "darwin":
            _mac_install(self)
        return self.window

    def run(self, after_start: Callable[[], None] | None = None) -> None:
        """Show the window and run the system's event loop on this (the main) thread until the
        app quits. On macOS a quit ends the process from inside this call (see terminating)."""

        def started():
            if not self.loaded.wait(LOAD_TIMEOUT) and not self.quitting:
                log.warning("the window did not show the page within %d s: opening the browser too", LOAD_TIMEOUT)
                _open_browser(self.url)
            if after_start:
                after_start()

        lang = self._language()
        self._webview.start(started, private_mode=False, storage_path=storage_dir(),
                            localization=LOCALIZATION.get(lang, {}))
        self._save()

    # ------------------------------------------------------------ what the icon and a second start do

    def show(self, hash: str = "") -> None:
        if self.window is None or self.quitting:
            return
        log.info("showing the window%s", f" at {hash}" if hash else "")
        if self._platform == "darwin":
            _mac_dock(True)
        if self._minimized:
            self.window.restore()
        self.window.show()
        self.hidden = False
        if hash:
            # Never on the macOS main thread: running a script waits for the engine's answer.
            threading.Thread(target=self._go, args=(hash,), daemon=True).start()

    def _go(self, hash: str) -> None:
        try:
            self.window.evaluate_js(f"window.location.hash = {json.dumps(hash)}")
        except Exception:  # noqa: BLE001
            log.exception("could not open %s in the window", hash)

    def open_in_browser(self) -> None:
        _open_browser(self.url)

    def hide(self, explain: bool = False) -> None:
        if self.window is None or self.quitting:
            return
        log.info("window closed: hiding it; the app keeps running in the %s",
                 "menu bar" if self._platform == "darwin" else "notification area")
        self.window.hide()
        self.hidden = True
        if self._platform == "darwin":
            _mac_dock(False)  # menu bar only again, as before there was a window
        tell = explain and not self._state.get("told_hidden")
        if tell:
            self._state["told_hidden"] = True
        self._save()
        text = HIDDEN.get(self._language(), HIDDEN["en"]).get(self._platform)
        if tell and text and self.notify:
            threading.Thread(target=self._tell, args=(text,), daemon=True).start()

    def _tell(self, text: str) -> None:
        try:
            self.notify(text)
        except Exception:  # noqa: BLE001 - a missing message is no reason to fail
            log.exception("could not show the message by the icon")

    def quit(self) -> None:
        """Quit for real: the icon's "Quit" (on macOS ⌘Q and signing out come in as terminating)."""
        if self.quitting:
            return
        if self.window is None:
            self.quitting = True
            self._on_quit()
            return
        if self._platform == "darwin":
            _mac_terminate()  # through terminating(), like ⌘Q
            return
        self.quitting = True
        self._save()
        self.window.destroy()  # the event loop ends; desktop.main then stops the server

    def terminating(self, reply: Callable[[bool], None]) -> int:
        """macOS asks whether the app may end (⌘Q, Quit in the icon's menu, signing out,
        shutting down). Stop the server first, then let it end: 2 = "answer later"."""
        log.info("quitting (asked by macOS)")
        self.quitting = True
        self._save()
        if self.window is not None:
            self.window.hide()

        def finish():
            try:
                self._on_quit()
            finally:
                reply(True)

        threading.Thread(target=finish, name="rprov-quit").start()
        return 2  # NSTerminateLater

    # ------------------------------------------------------------ the window's own events

    def _closing(self) -> bool:
        """pywebview's "closing": False keeps the window (it is hidden instead)."""
        if self.quitting:
            return True
        if not self._form_decides:
            self.hide(explain=True)
        return False

    def _loaded(self) -> None:
        if not self.loaded.is_set():
            log.info("window loaded %s", self.url)
        self.loaded.set()
        if self._platform == "win32":
            _windows_browser_keys(self.window)

    def _on_minimized(self) -> None:
        self._minimized = True

    def _on_restored(self) -> None:
        self._minimized = False

    def _on_resized(self, width, height) -> None:
        if not self._minimized:
            self._size = (int(width), int(height))

    def _before_show_windows(self) -> None:
        try:
            _windows_watch_close(self, self.window)
        except Exception:  # noqa: BLE001
            log.exception("could not watch why the window closes; closing it will hide it")

    def form_closing(self, reason: str, user: bool) -> bool:
        """Windows: the form is closing, and the form knows why. True lets it close."""
        if self.quitting:
            return True
        if user:
            self.hide(explain=True)
            return False
        # Windows is shutting down or signing out, or an installer closes the app to update it.
        log.info("Windows is closing the app (%s): quitting", reason)
        self.quitting = True
        self._save()
        return True

    def _save(self) -> None:
        width, height = self._size
        if (self._state.get("width"), self._state.get("height")) != (width, height):
            self._state.update(width=width, height=height)
        save_state(self.data_dir, self._state)


def _open_browser(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        log.exception("could not open a browser for %s", url)


# ---------------------------------------------------------------- macOS


_mac_shell: list[AppWindow] = []  # the window the app delegate answers for


def _mac_install(shell: AppWindow) -> None:
    """Answer the Dock icon and ⌘Q / signing out through pywebview's own app delegate: a
    subclass of it, set before pywebview makes its own."""
    _mac_shell[:] = [shell]
    from webview.platforms import cocoa

    if cocoa.BrowserView._shared_app_delegate is None:
        cocoa.BrowserView._shared_app_delegate = _mac_delegate_class(cocoa).alloc().init()


_delegate_class = []


def _mac_delegate_class(cocoa):
    if _delegate_class:
        return _delegate_class[0]
    import AppKit
    from PyObjCTools import AppHelper

    class RprovAppDelegate(cocoa.BrowserView.AppDelegate):
        def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible):
            # Opened again (Finder, Launchpad, Dock) while running: show the window.
            if _mac_shell:
                _mac_shell[0].show()
            return False

        def applicationShouldTerminate_(self, app):
            if not _mac_shell:
                return AppKit.NSTerminateNow
            return _mac_shell[0].terminating(
                lambda ok: AppHelper.callAfter(app.replyToApplicationShouldTerminate_, ok))

    _delegate_class.append(RprovAppDelegate)
    return RprovAppDelegate


def _mac_dock(visible: bool) -> None:
    """A Dock icon (and the app's menus) while the window is open; menu bar only while hidden."""
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except Exception:  # noqa: BLE001
        return
    app = AppKit.NSApplication.sharedApplication()
    policy = (AppKit.NSApplicationActivationPolicyRegular if visible
              else AppKit.NSApplicationActivationPolicyAccessory)
    AppHelper.callAfter(app.setActivationPolicy_, policy)


def _mac_terminate() -> None:
    import AppKit
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    AppHelper.callAfter(app.terminate_, None)


def mac_simulate_close(window) -> None:
    """The red close button, for the packaging check (pywebview's destroy() would not ask)."""
    import AppKit  # noqa: F401
    from PyObjCTools import AppHelper

    AppHelper.callAfter(window.native.performClose_, None)


# ---------------------------------------------------------------- Windows


def _windows_watch_close(shell: AppWindow, window) -> None:
    """pywebview only says "closing"; the form also says why. A close by you hides the window;
    Windows shutting down, signing out or an installer updating the app quits it."""
    from System.Windows.Forms import CloseReason

    def closing(_sender, args):
        try:
            user = args.CloseReason == CloseReason.UserClosing
            args.Cancel = not shell.form_closing(str(args.CloseReason), user)
        except Exception:  # noqa: BLE001
            log.exception("close handler failed")

    window.native.FormClosing += closing  # runs after pywebview's own handler
    shell._form_decides = True


def _windows_browser_keys(window) -> None:
    """The right-click menu (copy, paste) and the usual keys (Ctrl+P, Ctrl+F, zoom), which
    pywebview turns off outside its debug mode."""
    try:
        from System import Func, Type

        form = window.native

        def enable():
            settings = form.browser.webview.CoreWebView2.Settings
            settings.AreDefaultContextMenusEnabled = True
            settings.AreBrowserAcceleratorKeysEnabled = True

        form.Invoke(Func[Type](enable))
    except Exception:  # noqa: BLE001
        log.exception("could not turn on the right-click menu")
