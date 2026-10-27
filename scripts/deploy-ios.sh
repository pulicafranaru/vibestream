#!/usr/bin/env bash
# Build VibeStream for iOS and install it on paired, trusted, unlocked devices (Xcode, xcodegen).
#
# Usage:
#     scripts/deploy-ios.sh                 # the devices in IOS_DEVICES (.env)
#     scripts/deploy-ios.sh NAME            # paired devices whose name matches
#     scripts/deploy-ios.sh --all           # every paired, available device
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IOS_DIR="$ROOT/ios"

FILTER="${1:-}"
ALL=0
[ "$FILTER" = "--all" ] && { ALL=1; FILTER=""; }

# Xcode per invocation, so switching the active developer directory (sudo) is not needed.
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

source "$ROOT/scripts/env.sh"

# By identifier, since names can repeat; other paired devices must be asked for.
read -r -a TARGETS <<< "$(env_value IOS_DEVICES)"

APP_ID="$(require_env APP_ID "the bundle identifier, e.g. com.example.vibestream")"
TEAM="$(require_env APPLE_TEAM_ID "the Apple developer team that signs the app")"
PUBLIC_URL="$(require_env PUBLIC_URL "the server's public https address")"
LAN_URL="$(require_env LAN_URL "the server's address on the local network")"

[ -d "$DEVELOPER_DIR" ] || die "Xcode not found at $DEVELOPER_DIR"
command -v xcodegen >/dev/null || die "xcodegen is missing: brew install xcodegen"

cd "$IOS_DIR"

# A new build number on every build: iOS uses it to decide what to redo on install.
BUILD_FILE="$IOS_DIR/build-number"
[ -f "$BUILD_FILE" ] || echo 0 > "$BUILD_FILE"
BUILD=$(( $(cat "$BUILD_FILE") + 1 ))
echo "$BUILD" > "$BUILD_FILE"
say "Build $BUILD"

say "Generating the project"
# A plist names the plain-HTTP host as a dictionary key, so it cannot come from a build setting.
mkdir -p "$IOS_DIR/Generated"
sed -e "s#__PUBLIC_URL__#$PUBLIC_URL#g" \
    -e "s#__LAN_URL__#$LAN_URL#g" \
    -e "s#__LAN_HOST__#$(host_of "$LAN_URL")#g" \
    "$IOS_DIR/Info.template.plist" > "$IOS_DIR/Generated/Info.plist"
xcodegen generate >/dev/null

say "Building"
# Judge by the exit status: a failed build leaves the previous bundle in place.
LOG="$IOS_DIR/build/last-build.log"
mkdir -p "$IOS_DIR/build"
set +e
xcodebuild -project VibeStream.xcodeproj -scheme VibeStream -configuration Debug \
    -destination "generic/platform=iOS" -derivedDataPath build \
    CURRENT_PROJECT_VERSION="$BUILD" \
    PRODUCT_BUNDLE_IDENTIFIER="$APP_ID" DEVELOPMENT_TEAM="$TEAM" \
    build -allowProvisioningUpdates > "$LOG" 2>&1
STATUS=$?
set -e
grep -E "error:|warning: [A-Z]|BUILD" "$LOG" || true
[ "$STATUS" -eq 0 ] || die "the build failed (exit $STATUS). Full log: $LOG"

APP="$IOS_DIR/build/Build/Products/Debug-iphoneos/VibeStream.app"
[ -d "$APP" ] || die "the build produced no app bundle"
BUILT="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Info.plist")"
[ "$BUILT" = "$BUILD" ] || die "the bundle is build $BUILT, not $BUILD: it is stale"

say "Finding devices"
# Physical, paired devices only. Read the JSON: the table's columns move between Xcode versions.
DEVICE_JSON="$IOS_DIR/build/devices.json"
xcrun devicectl list devices --json-output "$DEVICE_JSON" >/dev/null 2>&1 \
    || die "devicectl could not list devices"
DEVICES=$(python3 - "$DEVICE_JSON" <<'PY'
import json, sys
for d in json.load(open(sys.argv[1]))["result"]["devices"]:
    if d["hardwareProperties"].get("reality") == "simulated":
        continue
    if d["connectionProperties"].get("pairingState") != "paired":
        continue
    print(d["deviceProperties"]["name"] + "\t" + d["identifier"])
PY
)
[ -n "$DEVICES" ] || die "no paired devices. Plug one in, unlock it and trust this Mac."

wanted() {
    local name="$1" id="$2"
    [ "$ALL" -eq 1 ] && return 0
    if [ -n "$FILTER" ]; then [[ "$name" == *"$FILTER"* ]] && return 0 || return 1; fi
    for target in "${TARGETS[@]}"; do [ "$id" = "$target" ] && return 0; done
    return 1
}

FAILED=0
MATCHED=0
while IFS=$'\t' read -r NAME ID; do
    wanted "$NAME" "$ID" || continue
    MATCHED=1
    say "Installing on $NAME"
    if ! xcrun devicectl device install app --device "$ID" "$APP" 2>&1 | tail -3; then
        printf '\033[1;31m  failed\033[0m\n'
        FAILED=1
    fi
done <<< "$DEVICES"

[ "$MATCHED" -eq 1 ] || die "none of the paired devices matched. Available:
$(echo "$DEVICES" | cut -f1 | sed 's/^/    /')"

if [ "$FAILED" -eq 0 ]; then
    printf '\n\033[1;32mInstalled build %s.\033[0m\n' "$BUILD"
else
    printf '\n\033[1;33mSome installs failed.\033[0m Unlock the device and retry.\n'
fi

cat <<EOF

  The app finds the server itself: $PUBLIC_URL first, then
  $LAN_URL if the name will not resolve on that network.

  Signed with a development profile, which expires after a year; rerun this
  to renew it.
EOF
