#!/bin/sh
set -eu
umask 077

: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGHOST:?PGHOST is required}"
: "${BACKUP_DIR:=/backups}"
: "${BACKUP_RETENTION_DAYS:=14}"
if [ -z "${PGSSLROOTCERT:-}" ]; then
    unset PGSSLROOTCERT
fi

case "$BACKUP_RETENTION_DAYS" in
    ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS must be a positive integer." >&2; exit 2 ;;
esac
if [ "$BACKUP_RETENTION_DAYS" -lt 1 ]; then
    echo "BACKUP_RETENTION_DAYS must be at least 1." >&2
    exit 2
fi

mkdir -p "$BACKUP_DIR"
timestamp=$(date -u '+%Y%m%dT%H%M%SZ')
temporary_path=$(mktemp "$BACKUP_DIR/.ares-$timestamp.XXXXXX")
suffix=${temporary_path##*.}
final_path="$BACKUP_DIR/ares-$timestamp-$suffix.dump"
cleanup() { rm -f "$temporary_path"; }
trap cleanup EXIT HUP INT TERM

if ! pg_dump --format=custom --no-owner --no-privileges --file="$temporary_path" --dbname="$PGDATABASE"; then
    echo "PostgreSQL backup failed; the incomplete file will be removed." >&2
    exit 1
fi
if ! pg_restore --list "$temporary_path" >/dev/null; then
    echo "PostgreSQL backup archive validation failed; the file will be removed." >&2
    exit 1
fi

mv "$temporary_path" "$final_path"
echo "Validated PostgreSQL backup created: $(basename "$final_path")"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'ares-*.dump' -mtime "+$BACKUP_RETENTION_DAYS" -print -delete
