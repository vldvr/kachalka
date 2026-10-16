#!/bin/bash
# Собирает «Качалка.app» и образ диска для текущей архитектуры Mac:
#   dist/Kachalka-<версия>-macOS-AppleSilicon.dmg или ...-macOS-Intel.dmg
set -euo pipefail
cd "$(dirname "$0")/../.."

PYTHON="${PYTHON:-python3}"
"$PYTHON" -m PyInstaller packaging/kachalka.spec --noconfirm --clean --distpath dist --workpath build

APP="dist/Качалка.app"
# Подпись без сертификата разработчика: на Apple Silicon без неё приложение не запустится вовсе.
codesign --force --deep --sign - "$APP"

VERSION="$("$PYTHON" -c 'import kachalka; print(kachalka.__version__)')"
if [ "$(uname -m)" = "arm64" ]; then ARCH="AppleSilicon"; else ARCH="Intel"; fi
DMG="dist/Kachalka-${VERSION}-macOS-${ARCH}.dmg"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Программы"
rm -f "$DMG"
hdiutil create -volname "Качалка" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null
echo "Готово: $DMG"
