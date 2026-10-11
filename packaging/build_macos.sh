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
rm -rf build/dmg "$DMG"
mkdir -p build/dmg
cp -R "$APP" build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -volname "Research History" -srcfolder build/dmg -ov -format UDZO "$DMG"
du -sh "$APP" "$DMG"

bash packaging/smoke_macos.sh "$APP"
echo "Done: $DMG"
