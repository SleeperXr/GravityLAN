#!/bin/sh
# GravityLAN container entrypoint.
#
# Started as root (the default), it gives the "gravitylan" user the UID/GID from
# PUID/PGID (default 1000:1000, Unraid: 99:100), makes the data directory writable
# for that user and drops to it before starting the server. Nmap keeps its file
# capabilities (setcap), so scans still work with --cap-add=NET_RAW/NET_ADMIN.
#
# Started without root (docker run --user ...), nothing is changed: the data
# directory must already be writable for that user.
set -eu

APP_USER=gravitylan
DATA_DIR="${GRAVITYLAN_DATA_DIR:-/app/data}"

log() {
    echo "[entrypoint] $*" >&2
}

fail_not_writable() {
    log "PERMISSION ERROR: Cannot write to data directory '$DATA_DIR' as UID $1 / GID $2."
    log "Fix it on the host, e.g.: chown -R $1:$2 /path/to/your/data"
    log "(on Unraid: chown -R $1:$2 /mnt/user/appdata/gravitylan)"
    exit 1
}

if [ "$(id -u)" != "0" ]; then
    # Running as a fixed non-root user: PUID/PGID cannot be applied.
    uid="$(id -u)"
    gid="$(id -g)"
    if [ -n "${PUID:-}${PGID:-}" ]; then
        log "Container runs as UID $uid / GID $gid (--user), PUID/PGID are ignored."
    fi
    mkdir -p "$DATA_DIR" 2>/dev/null || true
    if [ ! -w "$DATA_DIR" ]; then
        fail_not_writable "$uid" "$gid"
    fi
    exec "$@"
fi

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
case "$PUID$PGID" in
    *[!0-9]*)
        log "PUID and PGID must be numeric (got PUID='$PUID', PGID='$PGID')."
        exit 1
        ;;
esac
if [ "$PUID" = "0" ]; then
    log "PUID=0 is not supported; GravityLAN does not run as root. Use the owner of the data directory instead."
    exit 1
fi

# Align the user with PUID/PGID (-o: the IDs may already exist, e.g. GID 100 "users")
if [ "$(id -g "$APP_USER")" != "$PGID" ]; then
    groupmod -o -g "$PGID" "$APP_USER"
fi
if [ "$(id -u "$APP_USER")" != "$PUID" ] || [ "$(id -g "$APP_USER")" != "$PGID" ]; then
    usermod -o -u "$PUID" -g "$PGID" "$APP_USER" >/dev/null
fi

# Hand the data directory to the user. Only entries with a different owner are
# touched (fast on every later start). Other mounts below it are left alone:
# Docker volumes share one filesystem, so -xdev alone does not stop at them and
# their mount points are pruned explicitly.
chown_data_dir() {
    set --
    while read -r _ mount_point _; do
        case "$mount_point" in
            "$DATA_DIR"/*) set -- "$@" -path "$mount_point" -prune -o ;;
        esac
    done < /proc/self/mounts
    find "$DATA_DIR" -xdev "$@" \( ! -user "$PUID" -o ! -group "$PGID" \) \
        -exec chown -h "$PUID:$PGID" {} + 2>/dev/null
}
mkdir -p "$DATA_DIR"
if ! chown_data_dir; then
    log "Could not change the owner of everything in '$DATA_DIR' (network share or read-only mount?)."
fi

if ! setpriv --reuid="$PUID" --regid="$PGID" --clear-groups test -w "$DATA_DIR"; then
    fail_not_writable "$PUID" "$PGID"
fi

log "Starting GravityLAN as UID $PUID / GID $PGID."
export HOME="/home/$APP_USER" USER="$APP_USER" LOGNAME="$APP_USER"
exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
