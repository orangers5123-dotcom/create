#!/bin/bash
# Convert a PNG (ideally 1024x1024, square) into a macOS .icns app icon.
# macOS only -- uses the built-in `sips` and `iconutil` tools.
#
# Usage: ./make_icns.sh input.png output.icns
set -e

SRC="$1"
OUT="$2"

if [ -z "$SRC" ] || [ -z "$OUT" ]; then
  echo "Usage: $0 input.png output.icns"
  exit 1
fi
if [ ! -f "$SRC" ]; then
  echo "No such file: $SRC"
  exit 1
fi

WORKDIR=$(mktemp -d)
ICONSET="$WORKDIR/icon.iconset"
mkdir -p "$ICONSET"

for size in 16 32 64 128 256 512; do
  sips -z "$size" "$size" "$SRC" --out "$ICONSET/icon_${size}x${size}.png" > /dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" > /dev/null
done

iconutil -c icns "$ICONSET" -o "$OUT"
rm -rf "$WORKDIR"

echo "Wrote $OUT"
