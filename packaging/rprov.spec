# PyInstaller spec for the desktop app (DECISIONS D-044): one folder with its own Python,
# all dependencies, the built web UI and the files the app reads at run time.
#   uv run pyinstaller --noconfirm --clean packaging/rprov.spec
# Run packaging/prepare.py first (prebuilt verify.py and icons).
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
BUILD = ROOT / "build"
APP_NAME = "Research History"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

for needed in (ROOT / "web" / "dist" / "index.html", BUILD / "prebuilt" / "verify.py"):
    if not needed.exists():
        raise SystemExit(f"missing {needed}: build the web UI and run packaging/prepare.py first")

datas = [
    (str(ROOT / "web" / "dist"), "web/dist"),
    (str(ROOT / "app" / "report" / "templates"), "app/report/templates"),
    (str(ROOT / "fixtures" / "fsf_demo"), "fixtures/fsf_demo"),
    (str(ROOT / "fixtures" / "fsf_sample"), "fixtures/fsf_sample"),  # the sample research in practice (D-059)
    (str(ROOT / "core" / "provenance_core" / "certs"), "provenance_core/certs"),
    (str(BUILD / "prebuilt" / "verify.py"), "prebuilt"),
    # Export compares each timestamp's issuer with the test TSA to label test bundles; only its
    # two public certificates are needed. Its private key never goes into an installer.
    (str(ROOT / "core" / "provenance_core" / "providers" / "mock_tsa" / "mock-tsa-root.pem"), "provenance_core/providers/mock_tsa"),
    (str(ROOT / "core" / "provenance_core" / "providers" / "mock_tsa" / "mock-tsa.pem"), "provenance_core/providers/mock_tsa"),
]
assert not any("key" in Path(src).name for src, _ in datas), "a private key must never be packaged"
datas += copy_metadata("keyring")  # keyring finds its backends through package metadata
# The app's window (D-058): the scripts pywebview puts into the page (its PyInstaller hook only
# collects the WebView2 libraries, on Windows).
datas += collect_data_files("webview", subdir="js")

hiddenimports = collect_submodules("uvicorn") + collect_submodules("keyring.backends")
hiddenimports += ["pystray._win32", "webview.platforms.winforms", "webview.platforms.edgechromium",
                  "webview.platforms.mshtml"] if sys.platform == "win32" else []
hiddenimports += ["pystray._darwin", "webview.platforms.cocoa"] if sys.platform == "darwin" else []

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT), str(ROOT / "core")],
    datas=datas,
    hiddenimports=hiddenimports,
    # pywebview's other toolkits (Qt, GTK, CEF, Android) are not used on macOS or Windows.
    excludes=["tkinter", "pytest", "_pytest", "playwright", "webview.platforms.qt", "webview.platforms.gtk",
              "webview.platforms.cef", "webview.platforms.android", "qtpy", "gi"],
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = None
if sys.platform == "win32":
    icon = str(BUILD / "icons" / "app.ico")
elif sys.platform == "darwin" and (BUILD / "icons" / "app.icns").exists():
    icon = str(BUILD / "icons" / "app.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,  # no terminal window; everything goes to <data>/logs/app.log
    icon=icon,
    codesign_identity=None,  # ad-hoc signature on macOS (no Apple account needed)
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="org.rprov.research-history",
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            # Starts as a menu bar app; the window brings a Dock icon while it is open (D-058).
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
