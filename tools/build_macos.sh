#!/usr/bin/env bash
# macOS build: dist/AccessibleIPTVClient-vX.Y.Z-macos-<arch>.zip holding
# AccessibleIPTVClient.app with ffmpeg and libVLC bundled (see main.spec).
# Windows uses build.bat; Linux uses tools/build_deb.py.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}

[ "$(uname -s)" = Darwin ] || { echo "tools/build_macos.sh must run on macOS." >&2; exit 1; }
command -v ffmpeg >/dev/null || brew install ffmpeg
export IPTV_VLC_APP="${IPTV_VLC_APP:-/Applications/VLC.app}"
[ -d "$IPTV_VLC_APP" ] || brew install --cask vlc

"$PYTHON" -m pip install pyinstaller -r requirements.txt
"$PYTHON" -m PyInstaller --noconfirm --clean main.spec

app="dist/AccessibleIPTVClient.app"
bundle="$app/Contents/Frameworks"
codesign --force --deep --sign - "$app"

# The bundled tools must work without Homebrew or VLC.app behind them.
env -i PATH=/usr/bin:/bin "$bundle/ffmpeg" -hide_banner -version | head -1
PYTHON_VLC_LIB_PATH="$bundle/vlc/lib/libvlc.dylib" PYTHON_VLC_MODULE_PATH="$bundle/vlc/plugins" \
  "$PYTHON" -c 'import vlc, sys; i = vlc.Instance("--no-video"); print("libVLC", vlc.libvlc_get_version()); sys.exit(0 if i else "bundled libVLC did not start")'

# Launch check: the app must still be running after 15 seconds.
"$app/Contents/MacOS/IPTVClient" &
pid=$!
sleep 15
kill -0 "$pid" 2>/dev/null || { echo "IPTVClient exited during startup." >&2; exit 1; }
kill "$pid"; wait "$pid" 2>/dev/null || true

version="$("$PYTHON" -c 'import app_meta; print(app_meta.APP_VERSION)')"
zip="dist/AccessibleIPTVClient-v$version-macos-$(uname -m).zip"
ditto -c -k --sequesterRsrc --keepParent "$app" "$zip"
echo "macOS package: $zip"
