#!/usr/bin/env bash
#
# Pull the server's nightly database backups onto this machine, so a copy exists
# off the server. Complements fusionpilot-backup.sh, which only writes to the
# server's own disk — same-disk copies do not survive a lost server.
#
# Run from the repo root or anywhere:
#   bash deploy/backup/pull-backups.sh
# Optional: pass a destination directory as the first argument.
#
# Host/key come from deploy/.deploy.env (gitignored), so this file carries no
# real addresses and is safe to commit.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../.deploy.env"

REMOTE_DIR=/var/backups/fusionpilot
DEST=${1:-"$HOME/FusionPilot-backups"}
KEEP_LOCAL=30

SSH_OPTS=(-i "$DEPLOY_SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
HOST=${DEPLOY_HOST#*@}   # scp wants the key separately; DEPLOY_HOST is user@host

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

mkdir -p "$DEST"

log "listing backups on $HOST ..."
# List first, then copy file by file: a glob inside scp fails wholesale if the
# remote dir is empty, and per-file copies report exactly which file broke.
MAPFILE=()
while IFS= read -r name; do
    [[ -n "$name" ]] && MAPFILE+=("$name")
done < <(ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "ls -1t $REMOTE_DIR/*.sql.gz 2>/dev/null" | xargs -n1 basename)

if [[ ${#MAPFILE[@]} -eq 0 ]]; then
    log "WARNING: no .sql.gz files found in $REMOTE_DIR on the server."
    log "Has fusionpilot-backup.timer ever run? Check: systemctl list-timers fusionpilot-backup.timer"
    exit 1
fi

copied=0
skipped=0
corrupt=0
for name in "${MAPFILE[@]}"; do
    target="$DEST/$name"
    if [[ -f "$target" ]]; then
        skipped=$((skipped + 1))
        continue
    fi
    scp -q "${SSH_OPTS[@]}" "$DEPLOY_HOST:$REMOTE_DIR/$name" "$target" \
        || { log "FAILED to copy $name"; rm -f "$target"; corrupt=$((corrupt + 1)); continue; }
    if gzip -t "$target" 2>/dev/null; then
        copied=$((copied + 1))
        log "pulled $name ($(du -h "$target" | cut -f1))"
    else
        log "FAILED verification for $name (corrupt in transit) — deleted, will retry next run"
        rm -f "$target"
        corrupt=$((corrupt + 1))
    fi
done

# Retention: keep the newest KEEP_LOCAL files by name (names sort by date).
mapfile -t old < <(ls -1t "$DEST"/*.sql.gz 2>/dev/null | tail -n +$((KEEP_LOCAL + 1)))
if [[ ${#old[@]} -gt 0 ]]; then
    rm -f "${old[@]}"
    log "pruned ${#old[@]} old local copy(ies), keeping $KEEP_LOCAL"
fi

log "done: $copied new, $skipped already here, $corrupt failed. Local copies live in:"
log "  $DEST"

[[ $corrupt -eq 0 ]]
