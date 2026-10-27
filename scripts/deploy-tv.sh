#!/usr/bin/env bash
# Package the webOS launcher and install it on rooted LG TVs over SSH.
# The launcher loads the app from the server: reinstall only when webos/ changes.
# Needs ares-cli (npm i -g @webosose/ares-cli), and TV_HOSTS and TV_SSH_KEY in .env.
#
# Usage:
#     scripts/deploy-tv.sh [host ...]      (default: every host in TV_HOSTS)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/webos"
OUT_DIR="$ROOT/build"
STAGE="$OUT_DIR/webos"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
die() { printf '\n\033[1;31mERROR:\033[0m %s\n' "$1" >&2; exit 1; }

source "$ROOT/scripts/env.sh"

# webos/ holds placeholders; the package is built from a filled-in copy.
APP_ID="$(require_env APP_ID "the app id, e.g. com.example.vibestream")"
PUBLIC_URL="$(require_env PUBLIC_URL "the server's public https address")"
LAN_URL="$(require_env LAN_URL "the server's address on the local network")"

command -v ares-package >/dev/null || die "ares-cli is not installed.
  npm i -g @webosose/ares-cli"

if [ $# -gt 0 ]; then
  HOSTS=("$@")
else
  read -r -a HOSTS <<< "$(require_env TV_HOSTS "the TVs' addresses, separated by spaces")"
fi
KEY="$(require_env TV_SSH_KEY "the key for root on the TVs")"
KEY="${KEY/#\~/$HOME}"
[ -f "$KEY" ] || die "TV_SSH_KEY points at $KEY, which does not exist"
SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
tv() { ssh "${SSH_OPTS[@]}" "root@$1" "$2"; }
# luna-send prints nothing over SSH with -n 1, so it listens (-i) into a file,
# is stopped after a few seconds, and the file is read.
luna() {
  tv "$1" "f=/tmp/vibestream-luna.txt; (luna-send -i -f $2 '$3' > \$f 2>&1 &); sleep ${4:-3}; killall luna-send 2>/dev/null; cat \$f; rm -f \$f"
}

say "Checking the TVs are reachable"
for host in "${HOSTS[@]}"; do
  tv "$host" true 2>/dev/null || die "cannot reach root@$host over SSH.
  Is the TV on, and on this network?"
  echo "    $host"
done

# A new version on every package: the TV uses it to decide what to redo on install.
say "Bumping the build number"
VERSION="$(python3 - "$APP_DIR/appinfo.json" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as fh:
    info = json.load(fh)
major, minor, revision = (int(p) for p in info["version"].split("."))
info["version"] = f"{major}.{minor}.{revision + 1}"
with open(path, "w") as fh:
    json.dump(info, fh, indent=2)
    fh.write("\n")
print(info["version"])
PY
)"
echo "    $APP_ID $VERSION"

say "Packaging"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp "$APP_DIR"/*.json "$APP_DIR"/*.html "$APP_DIR"/*.png "$STAGE/"
# -i.bak, then remove it: the one in-place form GNU and BSD sed both read.
sed -i.bak -e "s#__APP_ID__#$APP_ID#g" "$STAGE/appinfo.json"
sed -i.bak -e "s#__PUBLIC_URL__#$PUBLIC_URL#g" -e "s#__LAN_URL__#$LAN_URL#g" "$STAGE/index.html"
rm -f "$STAGE/appinfo.json.bak" "$STAGE/index.html.bak"
ares-package "$STAGE" --outdir "$OUT_DIR" >/dev/null
IPK="$OUT_DIR/${APP_ID}_${VERSION}_all.ipk"
[ -f "$IPK" ] || die "expected $IPK but ares-package did not produce it"

FAILED=()
for host in "${HOSTS[@]}"; do
  say "Installing on $host"
  REMOTE="/tmp/$(basename "$IPK")"
  scp -q "${SSH_OPTS[@]}" "$IPK" "root@$host:$REMOTE"
  # luna-send holds its output back when piped, so it writes to a file on the set,
  # read once a second for up to two minutes.
  RESULT="$(tv "$host" "sh -s" <<REMOTE_SCRIPT
log=/tmp/vibestream-install.log
luna-send -i -f luna://com.webos.appInstallService/dev/install \
  '{"id":"$APP_ID","ipkUrl":"$REMOTE","subscribe":true}' > \$log 2>&1 &
pid=\$!
answer=timeout
i=0
while [ \$i -lt 120 ]; do
  if grep -q '"state": "installed"' \$log; then answer=installed; break; fi
  if grep -q '"state": "failed\|"errorText"\|"returnValue": false' \$log; then
    answer="failed \$(grep -o '"errorText": "[^"]*"' \$log | head -1)"; break
  fi
  sleep 1
  i=\$((i + 1))
done
kill \$pid 2>/dev/null
rm -f $REMOTE \$log
echo "\$answer"
REMOTE_SCRIPT
)" || true
  if [ "$RESULT" = "installed" ]; then
    tv "$host" "cat /media/developer/apps/usr/palm/applications/$APP_ID/appinfo.json" \
      | grep -q "\"$VERSION\"" || { echo "    installed, but the version on the set is not $VERSION"; FAILED+=("$host"); continue; }
    echo "    installed $VERSION"
    luna "$host" luna://com.webos.applicationManager/launch "{\"id\":\"$APP_ID\"}" >/dev/null
    # Check the set reports it in front a few seconds on.
    sleep 5
    if luna "$host" luna://com.webos.applicationManager/getForegroundAppInfo '{}' 2 \
        | grep -q "\"appId\": \"$APP_ID\""; then
      echo "    launched, and in front"
    else
      echo "    installed, but it is not the app in front after launching"
      FAILED+=("$host")
    fi
  else
    echo "    failed: ${RESULT:-no answer from the installer}"
    FAILED+=("$host")
  fi
done

[ ${#FAILED[@]} -eq 0 ] || die "not installed on: ${FAILED[*]}"
printf '\n\033[1;32mInstalled %s %s.\033[0m\n\n' "$APP_ID" "$VERSION"
cat <<EOF
  The launcher points at $PUBLIC_URL and falls back to
  $LAN_URL if the name will not resolve on the TV's network.

  The interface itself comes from the server: update the server, then
  reload the app on the TV.

  To look at a set: ssh -i $KEY root@<host>
EOF
