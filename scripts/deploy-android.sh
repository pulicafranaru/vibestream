#!/usr/bin/env bash
# Build VibeStream for Android and install it on what adb can see.
# Needs android-commandlinetools (platforms;android-35) and openjdk@17.
#
# Usage:
#     scripts/deploy-android.sh             # every device adb lists
#     scripts/deploy-android.sh emulator-5554
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANDROID_DIR="$ROOT/android"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

source "$ROOT/scripts/env.sh"

export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17}"
export ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
ADB="$ANDROID_HOME/platform-tools/adb"
[ -x "$ADB" ] || ADB="$(command -v adb || true)"
[ -n "$ADB" ] || die "adb not found"

APP_ID="$(require_env APP_ID "the application id, e.g. com.example.vibestream")"
PUBLIC_URL="$(require_env PUBLIC_URL "the server's public https address")"
LAN_URL="$(require_env LAN_URL "the server's address on the local network")"

# A new build number on every build: two different binaries must never share one.
BUILD_FILE="$ANDROID_DIR/build-number"
[ -f "$BUILD_FILE" ] || echo 0 > "$BUILD_FILE"
BUILD=$(( $(cat "$BUILD_FILE") + 1 ))
echo "$BUILD" > "$BUILD_FILE"
say "Build $BUILD"

echo "sdk.dir=$ANDROID_HOME" > "$ANDROID_DIR/local.properties"

say "Building"
(cd "$ANDROID_DIR" && ./gradlew -q :app:assembleDebug \
  -PvsAppId="$APP_ID" \
  -PvsBuild="$BUILD" \
  -PvsPublicUrl="$PUBLIC_URL" \
  -PvsLanUrl="$LAN_URL" \
  -PvsLanHost="$(host_of "$LAN_URL")")
APK="$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk"
[ -f "$APK" ] || die "no APK at $APK"

if [ -n "${1:-}" ]; then
  DEVICES=("$1")
else
  DEVICES=()
  while read -r serial; do DEVICES+=("$serial"); done < <("$ADB" devices | awk 'NR > 1 && $2 == "device" { print $1 }')
fi
[ "${#DEVICES[@]}" -gt 0 ] || die "no device: plug one in with USB debugging on, or start an emulator"

for device in "${DEVICES[@]}"; do
  say "Installing on $device"
  "$ADB" -s "$device" install -r "$APK" >/dev/null
done

printf '\n\033[1;32mInstalled build %s.\033[0m\n' "$BUILD"
