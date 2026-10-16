#!/bin/bash
# Перерисовывает иконки из icon.html: icon.png, AppIcon.icns (macOS) и kachalka.ico (Windows).
# Нужны macOS и Google Chrome. Готовые файлы лежат в репозитории, запускать надо только после правки icon.html.
set -euo pipefail
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

"$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --default-background-color=00000000 --window-size=1024,1024 \
  --screenshot="$TMP/icon.png" "file://$PWD/icon.html" >/dev/null 2>&1
sips -z 512 512 "$TMP/icon.png" --out icon.png >/dev/null

SET="$TMP/AppIcon.iconset"
mkdir -p "$SET"
for size in 16 32 128 256 512; do
  sips -z $size $size "$TMP/icon.png" --out "$SET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size * 2)) $((size * 2)) "$TMP/icon.png" --out "$SET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o AppIcon.icns

for size in 16 24 32 48 64 128 256; do
  sips -z $size $size "$TMP/icon.png" --out "$TMP/ico-$size.png" >/dev/null
done
python3 - "$TMP" <<'EOF'
import struct, sys
from pathlib import Path
# ICO с PNG внутри: Windows понимает такой формат начиная с Vista.
tmp = Path(sys.argv[1])
sizes = [16, 24, 32, 48, 64, 128, 256]
images = [(tmp / f"ico-{s}.png").read_bytes() for s in sizes]
header = struct.pack("<HHH", 0, 1, len(images))
offset = 6 + 16 * len(images)
entries = b""
for size, data in zip(sizes, images):
    entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
    offset += len(data)
Path("kachalka.ico").write_bytes(header + entries + b"".join(images))
EOF
echo "Готово: icon.png, AppIcon.icns, kachalka.ico"
