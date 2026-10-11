#!/usr/bin/env bash
#
# Nightly database backup. Installed to /usr/local/bin/fusionpilot-backup.sh by
# deploy/backup/install.sh and driven by fusionpilot-backup.timer.
#
# Run it by hand to take an extra backup before something risky:
#   sudo /usr/local/bin/fusionpilot-backup.sh
#
# Connects as the MySQL root user over the unix socket. root uses auth_socket on this host, which
# means "only a root process on this machine", and it is how the database is administered here
# anyway. Using it keeps the application password out of this file, out of `ps`, and out of the
# service environment entirely.
#
# Every check below exists because a backup script that reports success while producing nothing
# useful is worse than no backup at all. In particular mysqldump exits 0 for an empty schema, and a
# disk that filled up mid-write leaves a file that gzip will happily admit is corrupt.

set -euo pipefail

DB=fusionpilot
BACKUP_DIR=/var/backups/fusionpilot
KEEP=14
STAMP=$(date +%F)
TARGET="$BACKUP_DIR/$DB-$STAMP.sql.gz"
FAILED_MARKER="$BACKUP_DIR/LAST_BACKUP_FAILED"
SUCCESS_STAMP="$BACKUP_DIR/last-success.txt"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

fail() {
  log "FAILED: $*"
  # The marker is best-effort: if the reason we are failing is that the backup directory is
  # missing or unwritable, the redirect below cannot work, and the journal has the message anyway.
  {
    printf 'when: %s\n' "$(date '+%F %T')"
    printf 'why : %s\n' "$*"
  } > "$FAILED_MARKER" 2>/dev/null || true
  exit 1
}

# The unit's ProtectSystem=strict makes /var read-only except for paths listed in ReadWritePaths, and
# systemd only re-opens paths that already exist. So this directory is created at install time, and
# this line exists to fail loudly if that step was skipped rather than to be the thing that creates it.
mkdir -p "$BACKUP_DIR" || fail "cannot use $BACKUP_DIR (create it at install time: mkdir -p $BACKUP_DIR)"

# --- dump onto the same filesystem first, so an interrupted run never overwrites a good backup ----
TMP=$(mktemp "$BACKUP_DIR/.partial-$DB-$STAMP.XXXXXX.gz")
trap 'rm -f "$TMP"' EXIT

log "dumping $DB -> $TARGET"
mysqldump --single-transaction --quick --default-character-set=utf8mb4 "$DB" \
  | gzip -9 > "$TMP" \
  || fail "mysqldump or gzip returned non-zero"

# --- verify it is a real, complete dump ----------------------------------------------------------
gzip -t "$TMP" || fail "gzip -t says the archive is corrupt (usually a full disk)"

# mysqldump writes this as its final line; its absence means the dump was cut short.
tail -c 4096 <(zcat "$TMP") | grep -q 'Dump completed' \
  || fail "dump does not end with 'Dump completed' — it was truncated"

EXPECTED_TABLES=$(mysql -N -B -e \
  "select count(*) from information_schema.tables where table_schema='$DB'")
ACTUAL_TABLES=$(zcat "$TMP" | grep -c '^CREATE TABLE')
[ "$ACTUAL_TABLES" -ge "$EXPECTED_TABLES" ] \
  || fail "dump contains $ACTUAL_TABLES tables but the database has $EXPECTED_TABLES"

SIZE=$(du -h "$TMP" | cut -f1)

# --- swap into place atomically -----------------------------------------------------------------
mv -f "$TMP" "$TARGET"
trap - EXIT
log "ok: $TARGET ($SIZE, $ACTUAL_TABLES tables)"
printf '%s size=%s tables=%s file=%s\n' \
  "$(date '+%F %T')" "$SIZE" "$ACTUAL_TABLES" "$TARGET" > "$SUCCESS_STAMP"
rm -f "$FAILED_MARKER"

# --- retention ----------------------------------------------------------------------------------
# Count files, not days: a script that silently stopped running months ago should show up as
# "no recent backups", not as "nothing to delete".
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/$DB-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)))
if [ "${#OLD[@]}" -gt 0 ]; then
  rm -f "${OLD[@]}"
  log "pruned ${#OLD[@]} backup(s), keeping $KEEP"
fi

# --- this backup still lives on the machine it protects -----------------------------------------
# Same-disk backups do not survive a lost server. Copy them off with, from your own computer:
#   scp -i ~/.ssh/<key> root@<host>:/var/backups/fusionpilot/*.sql.gz ./fusionpilot-backups/
log "note: this copy is still on the same host — pull it off-machine to be a real backup"
