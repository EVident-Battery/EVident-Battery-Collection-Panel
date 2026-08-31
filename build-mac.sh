#!/bin/bash
# Build (and optionally sign + notarize) EvidentBatteryHub.app on an Apple Silicon Mac.
#
#   ./build-mac.sh            ad-hoc build (runs, but downloads hit Gatekeeper)
#   SIGN=1 ./build-mac.sh     Developer ID signed + notarized + stapled build
#
# Requirements (one-time, already set up on buildmac 2026-08-31):
#  - portable CPython venv at $VENV, created from a python-build-standalone
#    interpreter (uv python install 3.12). NEVER a Homebrew python: Homebrew
#    bottles carry MACOSX_DEPLOYMENT_TARGET = the build host's OS, and the
#    .app then refuses to launch on any older macOS (dyld minos check).
#  - for SIGN=1: a "Developer ID Application" identity in the keychain and the
#    App Store Connect API key below for notarytool.
set -euo pipefail

VENV="${VENV:-$HOME/venvs/collection-panel-pbs}"
SPEC=EvidentBatteryHub.spec
APP=dist/EvidentBatteryHub.app
ASC_KEY="$HOME/.appstoreconnect/private_keys/AuthKey_88Y8VV2GCC.p8"
ASC_KEY_ID=88Y8VV2GCC
ASC_ISSUER=3ca2babf-8e22-4da4-9f0a-4e37109c0957

cd "$(dirname "$0")"
echo "== building $(git rev-parse --short HEAD) with $("$VENV/bin/python" -V)"
tgt=$("$VENV/bin/python" -c 'import sysconfig;print(sysconfig.get_config_var("MACOSX_DEPLOYMENT_TARGET"))')
case "$tgt" in 1[0-4]*|11|12|13|14) ;; *) echo "FATAL: python deployment target is '$tgt' (Homebrew?) — bundle would require macOS $tgt+"; exit 1;; esac

if [ "${SIGN:-0}" = "1" ]; then
  EVB_CODESIGN_IDENTITY=$(security find-identity -v -p codesigning | awk -F'"' '/Developer ID Application/{print $2; exit}')
  [ -n "$EVB_CODESIGN_IDENTITY" ] || { echo "FATAL: no 'Developer ID Application' identity in keychain"; exit 1; }
  export EVB_CODESIGN_IDENTITY
  echo "== signing as: $EVB_CODESIGN_IDENTITY"
fi

rm -rf build dist
"$VENV/bin/python" -m PyInstaller --noconfirm --clean "$SPEC"

echo "== portability check (max allowed minos: 14.0)"
BAD=$(find "$APP" -type f \( -name '*.dylib' -o -name '*.so' -o -name 'Python' -o -path '*/MacOS/*' \) -print0 \
  | xargs -0 -n1 sh -c 'v=$(vtool -show-build "$0" 2>/dev/null | awk "/minos/{print \$2; exit}"); case "$v" in 14.[1-9]*|1[5-9].*|2[0-9].*) echo "$v $0";; esac')
[ -z "$BAD" ] || { echo "FATAL: binaries require macOS newer than 14:"; echo "$BAD" | head; exit 1; }
codesign --verify --deep --strict "$APP"

ZIP="dist/EvidentBatteryHub_macOS_arm64_$(git rev-parse --short HEAD).zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

if [ "${SIGN:-0}" = "1" ]; then
  echo "== notarizing (this waits on Apple, typically 1-10 min)"
  xcrun notarytool submit "$ZIP" --key "$ASC_KEY" --key-id "$ASC_KEY_ID" --issuer "$ASC_ISSUER" --wait
  xcrun stapler staple "$APP"
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"   # re-zip with the staple
  spctl -a -vv "$APP" 2>&1 | tail -2                        # final Gatekeeper verdict
fi

ls -la "$ZIP"
echo "== done"
