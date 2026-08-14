#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${BACKUP_ENABLED:-false}" != "true" ]]; then
    echo '{"level":"info","event":"backup_disabled"}'
    exec sleep infinity
fi

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
if [[ ! "${interval}" =~ ^[1-9][0-9]*$ ]]; then
    echo "BACKUP_INTERVAL_SECONDS must be a positive integer" >&2
    exit 64
fi

while true; do
    if ! /usr/local/bin/backup-postgres; then
        echo '{"level":"error","event":"postgres_backup_failed"}' >&2
    fi
    sleep "${interval}"
done
