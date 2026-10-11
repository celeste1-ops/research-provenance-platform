#!/usr/bin/env bash
# Build the macOS app and disk image (DECISIONS D-044). Run on a Mac from the repository root:
#   bash packaging/build_macos.sh
# Needs: uv, Node.js 22+, Xcode command line tools (iconutil, codesign, hdiutil).
# Produces dist/Research History.app and dist/ResearchHistory-<version>-macos-<arch>.dmg,
# then runs packaging/smoke_macos.sh against the app. Not signed with an Apple Developer ID:
# the app gets an ad-hoc signature, which Apple Silicon requires and which costs nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

ARCH="$(uname -m)"   # arm64 on Apple Silicon, x86_64 on Intel
VERSION="$(uv run python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
echo "Building Research History ${VERSION} for macOS ${ARCH}"

uv sync --extra ots --extra desktop --group package --locked
(cd web && npm ci && npm run build)
uv run python packaging/prepare.py
iconutil -c icns build/icons/app.iconset -o build/icons/app.icns

rm -rf "dist/Research History" "dist/Research History.app"
uv run pyinstaller --noconfirm --clean packaging/rprov.spec --distpath dist --workpath build/pyinstaller
APP="dist/Research History.app"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

DMG="dist/ResearchHistory-${VERSION}-macos-${ARCH}.dmg"
rm -f "$DMG"
# The window that opens with the disk image: the app and Applications side by side on a picture
# that says to drag one onto the other, then open the app from Applications (D-052).
tiffutil -cathidpicheck packaging/macos/dmg-background.png packaging/macos/dmg-background@2x.png \
  -out build/dmg-background.tiff
uv run dmgbuild -s packaging/macos/dmg_settings.py -D app="$APP" -D background=build/dmg-background.tiff \
  "Research History" "$DMG"
MNT="$(mktemp -d)"
hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MNT" >/dev/null
for item in "Research History.app" Applications .DS_Store .background; do
  [ -e "$MNT/$item" ] || { hdiutil detach "$MNT" >/dev/null; echo "disk image lacks $item"; exit 1; }
done
hdiutil detach "$MNT" >/dev/null
du -sh "$APP" "$DMG"

bash packaging/smoke_macos.sh "$APP"
echo "Done: $DMG"
