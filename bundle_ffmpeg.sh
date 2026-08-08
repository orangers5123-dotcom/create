#!/bin/bash
# Copies the locally-installed ffmpeg/ffprobe (e.g. via Homebrew) into
# vendor/ffmpeg_bin/ so PyInstaller can bundle them into the .app with
# --add-binary. This makes the packaged app immune to the PATH-visibility
# problem GUI apps hit when launched from Finder/`open` -- see
# davinci_auto_cut/ffmpeg_locate.py for the runtime side of this.
#
# Run this once (or again whenever you update ffmpeg) before building
# either app with PyInstaller; see silence_cut_app/README.md /
# create_text_app/README.md for the full --add-binary build command.
#
# Usage:
#   ./bundle_ffmpeg.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="$REPO_DIR/vendor/ffmpeg_bin"

FFMPEG_PATH="$(command -v ffmpeg || true)"
FFPROBE_PATH="$(command -v ffprobe || true)"

if [ -z "$FFMPEG_PATH" ] || [ -z "$FFPROBE_PATH" ]; then
  echo "ffmpeg/ffprobe not found on PATH. Install them first, e.g.:" >&2
  echo "  brew install ffmpeg" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
cp "$FFMPEG_PATH" "$DEST_DIR/ffmpeg"
cp "$FFPROBE_PATH" "$DEST_DIR/ffprobe"
chmod +x "$DEST_DIR/ffmpeg" "$DEST_DIR/ffprobe"

echo "Copied:"
echo "  $FFMPEG_PATH -> $DEST_DIR/ffmpeg"
echo "  $FFPROBE_PATH -> $DEST_DIR/ffprobe"
echo
echo "These are copies of your own installed binaries (still dynamically"
echo "linked against the same Homebrew libraries at their existing absolute"
echo "paths), so this only works for building an app to run on *this* Mac --"
echo "it's not a portable/redistributable static build."
echo
echo "Now build with, e.g.:"
echo "  pyinstaller --name \"App Name\" --windowed \\"
echo "    --add-binary \"vendor/ffmpeg_bin/ffmpeg:ffmpeg_bin\" \\"
echo "    --add-binary \"vendor/ffmpeg_bin/ffprobe:ffmpeg_bin\" \\"
echo "    ... run_xxx.py"
