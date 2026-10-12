#!/bin/sh
set -eu
umask 077

if [ "$#" -ne 1 ]; then
    echo "Usage: RESTORE_TARGET_DB=<empty-db> $0 <backup-file>" >&2
    exit 2
fi

backup_file=$1
: "${RESTORE_TARGET_DB:?Set RESTORE_TARGET_DB to a separately provisioned empty database}"
: "${RESTORE_SOURCE_DB:?Set RESTORE_SOURCE_DB to the source database name}"
: "${RESTORE_TARGET_HOST:?Set RESTORE_TARGET_HOST}"
: "${RESTORE_TARGET_USER:?Set RESTORE_TARGET_USER}"
: "${RESTORE_TARGET_PASSWORD:?Set RESTORE_TARGET_PASSWORD using a secret manager}"

if [ "$RESTORE_TARGET_DB" = "$RESTORE_SOURCE_DB" ]; then
    echo "Refusing to restore over the configured source database." >&2
    exit 2
fi
if [ ! -r "$backup_file" ]; then
    echo "Backup file is missing or unreadable." >&2
    exit 2
fi

export PGHOST="$RESTORE_TARGET_HOST"
export PGPORT="${RESTORE_TARGET_PORT:-5432}"
export PGUSER="$RESTORE_TARGET_USER"
export PGPASSWORD="$RESTORE_TARGET_PASSWORD"
export PGSSLMODE="${RESTORE_TARGET_SSLMODE:-verify-full}"
if [ -n "${RESTORE_TARGET_SSLROOTCERT:-}" ]; then
    export PGSSLROOTCERT="$RESTORE_TARGET_SSLROOTCERT"
else
    unset PGSSLROOTCERT
fi

if ! pg_restore --list "$backup_file" >/dev/null; then
    echo "The backup archive is invalid or unreadable." >&2
    exit 1
fi

has_objects=$(psql --dbname="$RESTORE_TARGET_DB" --set=ON_ERROR_STOP=1 --tuples-only --no-align --command="SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f'))")
if [ "$has_objects" != "f" ]; then
    echo "Refusing restore: the target database is not empty or cannot be inspected." >&2
    exit 2
fi

pg_restore --exit-on-error --no-owner --no-privileges --dbname="$RESTORE_TARGET_DB" "$backup_file"
echo "Restore completed to the separately provisioned target database. Validate it before directing application traffic."
