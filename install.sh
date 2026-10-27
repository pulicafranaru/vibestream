#!/usr/bin/env bash
# VibeStream: install, or update, on a Linux machine.
#
#     curl -fsSL https://raw.githubusercontent.com/pulicafranaru/vibestream/main/install.sh | sudo bash
# Run it again to update: the settings, the library and the database stay.
#
# Optional settings, as environment variables (sudo -E):
#   VIBESTREAM_DIR      where it lives            /opt/vibestream
#   VIBESTREAM_MEDIA    downloads and library     $VIBESTREAM_DIR/media
#   VIBESTREAM_PORT     the app's port            80, or 8100 if 80 is taken
#   VIBESTREAM_IMAGE    the image to run          ghcr.io/pulicafranaru/vibestream:latest
#   VIBESTREAM_NAME     container name prefix     vibestream
#   TORRENT_PORT        qBittorrent's peer port   38801
set -euo pipefail

REPO="pulicafranaru/vibestream"
DIR="${VIBESTREAM_DIR:-/opt/vibestream}"
NAME="${VIBESTREAM_NAME:-vibestream}"
# A plain browser User-Agent: downloads say nothing about who is installing.
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
APP_UID=1000
APP_GID=1000

bold() { printf '\033[1m%s\033[0m' "$1"; }
say() { printf '\n\033[1;38;5;208m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$1" >&2; }
die() { printf '\n\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }
fetch() { curl -fsSL -A "$UA" "$@"; }

if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null || die "run this as root"
  # Piped in, there is no file to run again: say how instead.
  [ -f "${BASH_SOURCE[0]:-}" ] || die "run it with sudo: curl -fsSL ... | sudo bash"
  exec sudo -E bash "${BASH_SOURCE[0]}" "$@"
fi

[ "$(uname -s)" = Linux ] || die "VibeStream installs on Linux"
case "$NAME" in
  [a-zA-Z0-9]*) [ -z "${NAME//[a-zA-Z0-9_.-]/}" ] || die "VIBESTREAM_NAME may only have letters, digits, _ . and -" ;;
  *) die "VIBESTREAM_NAME must start with a letter or digit" ;;
esac
case "$(uname -m)" in
  x86_64 | amd64 | aarch64 | arm64) ;;
  *) die "this processor ($(uname -m)) is not supported: x86_64 or arm64 only" ;;
esac
command -v curl >/dev/null || die "curl is needed"

# In a subshell: os-release sets NAME, which this script also uses.
OS_ID="$( (. /etc/os-release 2>/dev/null; echo "${ID:-}") )"
OS_LIKE="$( (. /etc/os-release 2>/dev/null; echo "${ID_LIKE:-}") )"

install_docker() {
  say "Installing Docker"
  case " $OS_ID $OS_LIKE " in
    *" rhel "* | *" centos "* | *" fedora "* | *" rocky "* | *" almalinux "*)
      # get.docker.com does not know every RHEL rebuild; the CentOS packages fit them all.
      local repo="centos"
      [ "$OS_ID" = fedora ] && repo="fedora"
      dnf -y -q install dnf-plugins-core
      fetch "https://download.docker.com/linux/$repo/docker-ce.repo" -o /etc/yum.repos.d/docker-ce.repo
      dnf -y -q install docker-ce docker-ce-cli containerd.io docker-compose-plugin
      ;;
    *)
      fetch https://get.docker.com | sh
      ;;
  esac
  systemctl enable --now docker >/dev/null 2>&1 || service docker start
}

if ! command -v docker >/dev/null; then
  install_docker
fi
docker info >/dev/null 2>&1 || systemctl start docker 2>/dev/null || die "Docker is installed but not running"
docker compose version >/dev/null 2>&1 || die "Docker is here, but not its compose plugin: install docker-compose-plugin"

ENV_FILE="$DIR/.env"
FIRST=true
if [ -f "$ENV_FILE" ]; then
  FIRST=false
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

IMAGE="${VIBESTREAM_IMAGE:-${IMAGE:-ghcr.io/$(printf '%s' "$REPO" | tr '[:upper:]' '[:lower:]'):latest}}"
# 80 when free, so the bare hostname opens it in a browser; otherwise 8100.
port_taken() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }
if [ -z "${VIBESTREAM_PORT:-${PORT:-}}" ]; then
  if port_taken 80; then PORT=8100; else PORT=80; fi
fi
PORT="${VIBESTREAM_PORT:-${PORT}}"
TORRENT_PORT="${TORRENT_PORT:-38801}"

free_gb() { df -Pk "$1" 2>/dev/null | awk 'NR==2 { printf "%d", $4 / 1048576 }'; }

if [ -z "${VIBESTREAM_MEDIA:-}" ] && [ -n "${MEDIA:-}" ]; then
  VIBESTREAM_MEDIA="$MEDIA"
fi
if [ -z "${VIBESTREAM_MEDIA:-}" ]; then
  VIBESTREAM_MEDIA="$DIR/media"
  # First install with a terminal only. Piped, the keyboard is /dev/tty: open it to test (-r/-w lie).
  if $FIRST && (: </dev/tty >/dev/tty) 2>/dev/null; then
    probe="$VIBESTREAM_MEDIA"
    while [ ! -d "$probe" ]; do probe="$(dirname "$probe")"; done
    {
      printf '\nWhere should films and shows be kept? They need room: tens of GB each.\n'
      printf 'Press Enter for %s (%s GB free there), or type another folder: ' \
        "$(bold "$VIBESTREAM_MEDIA")" "$(free_gb "$probe")"
    } >/dev/tty
    read -r answer </dev/tty || answer=""
    if [ -n "$answer" ]; then
      case "$answer" in /*) VIBESTREAM_MEDIA="${answer%/}" ;; *) die "that is not a full path (starting with /)" ;; esac
    fi
  fi
fi
MEDIA="$(printf '%s' "$VIBESTREAM_MEDIA" | tr -s /)"
[ "$MEDIA" = / ] || MEDIA="${MEDIA%/}"
# Sourced as root by a later run and written into compose: plain characters only.
media_ok='^/[A-Za-z0-9/._ -]*$'
[[ "$MEDIA" =~ $media_ok ]] \
  || die "the media folder ($MEDIA) may only have letters, digits, spaces, / . _ and -"
case "${MEDIA%/}/" in
  */./* | */../*) die "the media folder ($MEDIA) may not have . or .. in it" ;;
  / | /bin/ | /boot/ | /dev/ | /etc/ | /home/ | /lib/ | /lib32/ | /lib64/ | /libx32/ \
  | /media/ | /mnt/ | /opt/ | /proc/ | /root/ | /run/ | /sbin/ | /snap/ | /srv/ \
  | /sys/ | /tmp/ | /usr/ | /var/ | /var/lib/ \
  | /bin/* | /boot/* | /dev/* | /etc/* | /lib/* | /lib32/* | /lib64/* | /libx32/* \
  | /proc/* | /run/* | /sbin/* | /sys/* | /usr/*)
    die "$MEDIA is a system folder: choose one of its own, such as /srv/media" ;;
esac
# A home folder itself belongs to its user, not to VibeStream.
HOMES="$(getent passwd 2>/dev/null | cut -d: -f6 || true)"
case $'\n'"$HOMES"$'\n' in
  *$'\n'"$MEDIA"$'\n'*) die "$MEDIA is a home folder: choose a folder inside it, such as $MEDIA/VibeStream" ;;
esac

if $FIRST; then
  QBIT_PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24 || true)"
  TZ_NAME="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)"
else
  [ -n "${QBIT_PASSWORD:-}" ] || die "$ENV_FILE has no QBIT_PASSWORD"
  TZ_NAME="${TZ:-UTC}"
fi

say "Writing $DIR"
mkdir -p "$DIR/data" "$DIR/qbittorrent/qBittorrent"
# Both containers run as $APP_UID, so each can write what the other made.
chown "$APP_UID:$APP_GID" "$DIR/data" "$DIR/qbittorrent" "$DIR/qbittorrent/qBittorrent"

# Chown a media folder only if this run made it or it is empty, never recursively:
# a folder already holding someone's files keeps its owner.
own_media_dir() {
  if [ ! -d "$1" ]; then
    mkdir -p "$1"
    chown "$APP_UID:$APP_GID" "$1"
  elif [ "$(stat -c %u "$1")" != "$APP_UID" ]; then
    if [ -z "$(ls -A "$1")" ]; then
      chown "$APP_UID:$APP_GID" "$1"
    else
      warn "$1 already has files and belongs to someone else: left as it is, so VibeStream may not be able to write there"
    fi
  fi
}
for d in "$MEDIA" "$MEDIA/downloads" "$MEDIA/library" "$MEDIA/library/Movies" "$MEDIA/library/Shows"; do
  own_media_dir "$d"
done
# Holds the indexer passkey, service keys and qBittorrent password: app user only.
chmod 700 "$DIR/data" "$DIR/qbittorrent" "$DIR/qbittorrent/qBittorrent"

umask 077
cat >"$ENV_FILE" <<EOF
# Kept on updates. Deleted, the next run asks again and makes new qBittorrent settings.
IMAGE="$IMAGE"
NAME="$NAME"
PORT="$PORT"
TORRENT_PORT="$TORRENT_PORT"
MEDIA="$MEDIA"
TZ="$TZ_NAME"
QBIT_PASSWORD="$QBIT_PASSWORD"
EOF
umask 022

# Intel or AMD GPU, for the transcode used when a TV cannot play a file as it is.
DEVICES=""
if [ -e /dev/dri ]; then
  DEVICES="    devices:
      - /dev/dri:/dev/dri"
  # The nodes are 0660 for render/video, which the app user is not in: add those gids.
  GROUPS_ADD=""
  for gid in $(stat -c %g /dev/dri/card* /dev/dri/renderD* 2>/dev/null | sort -un || true); do
    [ "$gid" = 0 ] || GROUPS_ADD="$GROUPS_ADD
      - \"$gid\""
  done
  [ -z "$GROUPS_ADD" ] || DEVICES="$DEVICES
    group_add:$GROUPS_ADD"
fi

cat >"$DIR/docker-compose.yml" <<EOF
# Rewritten on every update: change .env, not this.
name: $NAME

services:
  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:5.1.2
    container_name: \${NAME}-qbittorrent
    environment:
      - PUID=$APP_UID
      - PGID=$APP_GID
      - TZ=\${TZ}
      - WEBUI_PORT=8081
      - TORRENTING_PORT=\${TORRENT_PORT}
    volumes:
      - ./qbittorrent:/config:z
      # Same path in both containers: VibeStream hardlinks the files qBittorrent names.
      - \${MEDIA}:/data:z
    ports:
      # Its web interface only on this machine: VibeStream drives it.
      - "127.0.0.1:8101:8081"
      - "\${TORRENT_PORT}:\${TORRENT_PORT}/tcp"
      - "\${TORRENT_PORT}:\${TORRENT_PORT}/udp"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:8081 >/dev/null || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s

  vibestream:
    image: \${IMAGE}
    container_name: \${NAME}-api
    environment:
      - TZ=\${TZ}
      - VIBESTREAM_DB_PATH=/app/data/vibestream.db
      - QBIT_URL=http://qbittorrent:8081
      - QBIT_USERNAME=admin
      - QBIT_PASSWORD=\${QBIT_PASSWORD}
      - QBIT_DOWNLOAD_DIR=/data/downloads
      - LIBRARY_MOVIES_DIR=/data/library/Movies
      - LIBRARY_SHOWS_DIR=/data/library/Shows
    volumes:
      - ./data:/app/data:z
      # One mount for downloads and library: a hardlink cannot cross mounts, even on one disk.
      - \${MEDIA}:/data:z
$DEVICES
    ports:
      - "\${PORT}:8000"
    depends_on:
      qbittorrent:
        condition: service_healthy
    restart: unless-stopped
EOF

say "Downloading VibeStream and qBittorrent"
cd "$DIR"
# One at a time: in one pull, the first to fail cancels the other.
docker compose pull --quiet qbittorrent || die "could not download qBittorrent"
PULL_LOG="$(mktemp)"
if ! docker compose pull --quiet vibestream 2>"$PULL_LOG"; then
  # A copy loaded by hand (docker load) is used when there is no download.
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    warn "could not download $IMAGE; using the copy already on this machine"
  else
    cat "$PULL_LOG" >&2
    rm -f "$PULL_LOG"
    die "could not download $IMAGE"
  fi
fi
rm -f "$PULL_LOG"

QBT_CONF="$DIR/qbittorrent/qBittorrent/qBittorrent.conf"
# Rewritten when empty or after a new password, or qBittorrent would refuse VibeStream.
if $FIRST || [ ! -s "$QBT_CONF" ]; then
  # A running qBittorrent saves its settings as it stops, over these.
  docker compose stop qbittorrent >/dev/null 2>&1 || true
  # No ".!qB" suffix (it breaks playing files as they arrive); written aside, then moved in.
  QBT_NEW="$(mktemp "$QBT_CONF.XXXXXX")"
  # By name only: a value on the command line is readable in ps.
  export QBIT_PASSWORD
  if ! docker run --rm -e QBIT_PASSWORD "$IMAGE" \
    python -m vibestream.tools.qbt_config >"$QBT_NEW" || [ ! -s "$QBT_NEW" ]; then
    rm -f "$QBT_NEW"
    die "could not write the qBittorrent settings"
  fi
  sed -i "s/^Session\\\\Port=.*/Session\\\\Port=$TORRENT_PORT/" "$QBT_NEW"
  chown "$APP_UID:$APP_GID" "$QBT_NEW"
  mv -f "$QBT_NEW" "$QBT_CONF"
fi
chmod 600 "$QBT_CONF"

open_ports() {
  if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd -q --permanent --add-port="$PORT/tcp"
    firewall-cmd -q --permanent --add-port="$TORRENT_PORT/tcp"
    firewall-cmd -q --permanent --add-port="$TORRENT_PORT/udp"
    firewall-cmd -q --reload
    echo "opened $PORT and $TORRENT_PORT in firewalld"
  elif command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$PORT/tcp" >/dev/null
    ufw allow "$TORRENT_PORT" >/dev/null
    echo "opened $PORT and $TORRENT_PORT in ufw"
  fi
}

say "Starting"
docker compose up -d --remove-orphans
open_ports

for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 \
  || die "VibeStream did not start. Its log: docker logs $NAME-api"

# Each "|| true": with no default route ip fails, and pipefail would end the script.
ADDRESS="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{ for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1) }' || true)"
[ -n "$ADDRESS" ] || ADDRESS="$(hostname -I 2>/dev/null | awk '{ print $1 }' || true)"
[ -n "$ADDRESS" ] || ADDRESS="this-machine"
URL="http://$ADDRESS"
[ "$PORT" = 80 ] || URL="$URL:$PORT"

CLAIMED="$(curl -fsS "http://127.0.0.1:$PORT/api/admin/auth/state" | grep -o '"configured":[a-z]*' | cut -d: -f2 || true)"

printf '\n\033[1;32mVibeStream is running.\033[0m\n\n'
if [ "$CLAIMED" = false ]; then
  CODE="$(docker logs "$NAME-api" 2>&1 | grep -o 'admin setup code: [A-Z0-9-]*' | tail -n 1 | awk '{ print $4 }' || true)"
  printf '  1. Open      %s\n' "$(bold "$URL/admin")"
  printf '  2. Enter     %s   (the setup code)\n' "$(bold "${CODE:-see: docker logs $NAME-api | grep 'setup code'}")"
  printf '  3. Choose the admin password, and the setup walks you through the rest.\n'
else
  printf '  Updated. The app:   %s\n  The admin:         %s\n' "$(bold "$URL")" "$(bold "$URL/admin")"
fi
printf '\n  Films and shows:    %s\n  Everything else:    %s\n' "$MEDIA" "$DIR"
printf '  To update, run the same command again.\n\n'
