#!/usr/bin/env bash
# VibeStream: install, or update, on a Linux machine.
#
#     curl -fsSL https://raw.githubusercontent.com/pulicafranaru/vibestream/main/install.sh | sudo bash
# Run it again to update. "sudo bash -s -- rollback" undoes the last update.
#
# Optional settings, as environment variables (sudo -E):
#   VIBESTREAM_DIR      where it lives            /opt/vibestream
#   VIBESTREAM_MEDIA    downloads and library     $VIBESTREAM_DIR/media
#   VIBESTREAM_PORT     the app's port            80, or 8100 if 80 is taken
#   VIBESTREAM_VERSION  a release to stay on      latest, 1.2.0, or edge (main, untested)
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
# Backups kept, each with the image it was taken under.
KEEP_BACKUPS=3

ACTION="${1:-install}"

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
case "$ACTION" in
  install | rollback) ;;
  *) die "unknown command: $ACTION (rollback is the only one)" ;;
esac
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

mkdir -p "$DIR"
if command -v flock >/dev/null; then
  exec 9>"$DIR/.lock"
  flock -n 9 || die "another install or update is running"
fi

ENV_FILE="$DIR/.env"
FIRST=true
if [ -f "$ENV_FILE" ]; then
  FIRST=false
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

REGISTRY="ghcr.io/$(printf '%s' "$REPO" | tr '[:upper:]' '[:lower:]')"
if [ -n "${VIBESTREAM_VERSION:-}" ]; then
  [[ "$VIBESTREAM_VERSION" =~ ^(latest|edge|v?[0-9]+\.[0-9]+(\.[0-9]+)?)$ ]] \
    || die "VIBESTREAM_VERSION is latest, edge or a release such as 1.2.0"
  IMAGE="$REGISTRY:${VIBESTREAM_VERSION#v}"
fi
IMAGE="${VIBESTREAM_IMAGE:-${IMAGE:-$REGISTRY:latest}}"

# The version an image says it is, or its commit when it is not a release.
image_version() {
  local v r
  v="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$1" 2>/dev/null || true)"
  r="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1" 2>/dev/null || true)"
  case "$v" in
    [0-9]*) printf '%s' "$v" ;;
    *) if [ -n "$r" ]; then printf 'build %s' "${r:0:7}"; else printf 'unknown'; fi ;;
  esac
}

# The name in the registry that holds the same image: its release, else its commit.
image_pin() {
  local v r
  v="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}' "$1" 2>/dev/null || true)"
  r="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1" 2>/dev/null || true)"
  if [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then printf '%s:%s' "$REGISTRY" "$v"
  elif [ -n "$r" ]; then printf '%s:sha-%s' "$REGISTRY" "${r:0:7}"
  fi
}

healthy() {
  for _ in $(seq 1 90); do
    curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && return 0
    # Crashing over and over: no point waiting out the three minutes.
    [ "$(docker inspect -f '{{.RestartCount}}' "$NAME-api" 2>/dev/null || echo 0)" -lt 3 ] || return 1
    sleep 2
  done
  return 1
}

# Puts back the database, settings and image a backup was taken with.
restore() {
  local b="$1" img
  cd "$DIR"
  docker compose stop vibestream >/dev/null 2>&1 || true
  rm -f data/vibestream.db data/vibestream.db-wal data/vibestream.db-shm
  cp -p "$b"/vibestream.db* data/
  cp -p "$b/env" "$ENV_FILE"
  [ ! -f "$b/docker-compose.yml" ] || cp -p "$b/docker-compose.yml" docker-compose.yml
  img="$( (. "$b/env"; printf '%s' "$IMAGE") )"
  docker tag "$NAME-rollback:$(basename "$b")" "$img"
  docker compose up -d --remove-orphans
}

# Used up: the next rollback goes one version further back.
forget() {
  docker rmi "$NAME-rollback:$(basename "$1")" >/dev/null 2>&1 || true
  rm -rf "$1"
}

rollback() {
  $FIRST && die "VibeStream is not installed in $DIR"
  local b stamp version pin answer
  b="$(find "$DIR/backups" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -n 1)"
  [ -n "$b" ] || die "there is no backup in $DIR/backups: one is taken at every update"
  stamp="$(basename "$b")"
  docker image inspect "$NAME-rollback:$stamp" >/dev/null 2>&1 \
    || die "the image saved with the backup in $b is no longer on this machine"
  version="$(cat "$b/version" 2>/dev/null || echo unknown)"
  printf '\nBack to VibeStream %s, with the database as it was on %s UTC.\n' \
    "$(bold "$version")" "${stamp:0:4}-${stamp:4:2}-${stamp:6:2} ${stamp:9:2}:${stamp:11:2}"
  printf 'What happened since (downloads started, ratings, what was watched) is forgotten.\n'
  if (: </dev/tty >/dev/tty) 2>/dev/null; then
    printf 'Go back? [y/N] ' >/dev/tty
    read -r answer </dev/tty || answer=""
    case "$answer" in [yY]*) ;; *) die "nothing was changed" ;; esac
  fi
  say "Going back to $version"
  restore "$b"
  # Stays on it: the next run would otherwise fetch the version just left.
  pin="$(image_pin "$NAME-rollback:$stamp")"
  if [ -n "$pin" ]; then
    docker tag "$NAME-rollback:$stamp" "$pin"
    sed -i "s|^IMAGE=.*|IMAGE=\"$pin\"|" "$ENV_FILE"
    docker compose up -d --remove-orphans
  fi
  healthy || die "VibeStream $version did not start either. Its log: docker logs $NAME-api"
  forget "$b"
  printf '\n\033[1;32mVibeStream %s is running again.\033[0m\n\n' "$version"
  printf '  Updates stay paused on this version. To follow releases again:\n'
  printf '    curl -fsSL https://raw.githubusercontent.com/%s/main/install.sh | sudo VIBESTREAM_VERSION=latest bash\n\n' "$REPO"
  exit 0
}

[ "$ACTION" = rollback ] && rollback
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

OLD_ID=""
if ! $FIRST; then
  OLD_ID="$(docker inspect -f '{{.Image}}' "$NAME-api" 2>/dev/null || true)"
  if [ -f "$DIR/data/vibestream.db" ]; then
    need_kb=$(( $(du -ck "$DIR"/data/vibestream.db* | tail -n 1 | cut -f1) + 102400 ))
    have_kb="$(df -Pk "$DIR" | awk 'NR==2 { print $4 }')"
    [ "$have_kb" -gt "$need_kb" ] \
      || die "$DIR needs $((need_kb / 1024)) MB free for the backup taken before an update. Nothing was changed."
  fi
  # The settings as they were, for the backup.
  PREVIOUS="$(mktemp -d)"
  trap 'rm -rf "$PREVIOUS"' EXIT
  cp -p "$ENV_FILE" "$PREVIOUS/env"
  [ ! -f "$DIR/docker-compose.yml" ] || cp -p "$DIR/docker-compose.yml" "$PREVIOUS/"
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
QBT_IMAGE="$(docker compose config --images | grep -m1 qbittorrent || true)"
if ! docker compose pull --quiet qbittorrent; then
  # Pinned, so the copy already here is the same one: an update need not stop on a registry blip.
  docker image inspect "$QBT_IMAGE" >/dev/null 2>&1 || die "could not download qBittorrent"
  warn "could not download qBittorrent; using the copy already on this machine"
fi
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

NEW_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE")"
BACKUP=""
# Stopped first, so the copy is whole; the image is kept under a local name for rollback.
if [ -n "$OLD_ID" ] && [ "$OLD_ID" != "$NEW_ID" ] && [ -f "$DIR/data/vibestream.db" ]; then
  say "Backing up the database"
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  BACKUP="$DIR/backups/$stamp"
  mkdir -p "$BACKUP"
  chmod 700 "$DIR/backups"
  docker compose stop vibestream >/dev/null
  cp -p "$DIR"/data/vibestream.db* "$BACKUP/"
  cp -p "$PREVIOUS"/* "$BACKUP/"
  image_version "$OLD_ID" >"$BACKUP/version"
  docker tag "$OLD_ID" "$NAME-rollback:$stamp"
  find "$DIR/backups" -mindepth 1 -maxdepth 1 -type d | sort | head -n "-$KEEP_BACKUPS" | while read -r old; do
    docker rmi "$NAME-rollback:$(basename "$old")" >/dev/null 2>&1 || true
    rm -rf "$old"
  done
fi

say "Starting"
started=true
docker compose up -d --remove-orphans || started=false
open_ports
$started && healthy || started=false

if ! $started; then
  [ -n "$BACKUP" ] || die "VibeStream did not start. Its log: docker logs $NAME-api"
  docker logs --tail 300 "$NAME-api" >"$DIR/update-failed.log" 2>&1 || true
  old_version="$(cat "$BACKUP/version")"
  warn "VibeStream $(image_version "$NEW_ID") did not start: putting $old_version back"
  restore "$BACKUP"
  healthy || die "the previous version did not start either. Its log: docker logs $NAME-api"
  forget "$BACKUP"
  die "the update did not start, so $old_version is running again, its database as it was. What the new version said: $DIR/update-failed.log"
fi

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
  if [ -n "$BACKUP" ]; then
    printf '  Updated from %s to %s.\n' "$(cat "$BACKUP/version")" "$(bold "$(image_version "$NEW_ID")")"
    printf '  The database before it:  %s\n' "$BACKUP"
  else
    printf '  Already the newest: %s.\n' "$(bold "$(image_version "$NEW_ID")")"
  fi
  case "$IMAGE" in
    "$REGISTRY:latest") ;;
    *) printf '  Staying on %s. VIBESTREAM_VERSION=latest follows releases again.\n' "${IMAGE##*:}" ;;
  esac
  printf '\n  The app:            %s\n  The admin:          %s\n' "$(bold "$URL")" "$(bold "$URL/admin")"
fi
printf '\n  Films and shows:    %s\n  Everything else:    %s\n' "$MEDIA" "$DIR"
printf '  To update, run the same command again. To undo the last update, add: -s -- rollback\n\n'
