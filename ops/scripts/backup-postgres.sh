#!/usr/bin/env bash
set -Eeuo pipefail

required=(
    POSTGRES_HOST
    POSTGRES_DB
    POSTGRES_USER
    POSTGRES_PASSWORD_FILE
    RESTIC_REPOSITORY
    RESTIC_PASSWORD_FILE
    AWS_ACCESS_KEY_ID_FILE
    AWS_SECRET_ACCESS_KEY_FILE
)

for variable_name in "${required[@]}"; do
    if [[ -z "${!variable_name:-}" ]]; then
        echo "Missing required variable: ${variable_name}" >&2
        exit 64
    fi
done

for secret_file in \
    "${POSTGRES_PASSWORD_FILE}" \
    "${RESTIC_PASSWORD_FILE}" \
    "${AWS_ACCESS_KEY_ID_FILE}" \
    "${AWS_SECRET_ACCESS_KEY_FILE}"; do
    if [[ ! -r "${secret_file}" ]]; then
        echo "Secret file is not readable: ${secret_file}" >&2
        exit 66
    fi
done

export PGPASSWORD
export AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY
PGPASSWORD="$(<"${POSTGRES_PASSWORD_FILE}")"
AWS_ACCESS_KEY_ID="$(<"${AWS_ACCESS_KEY_ID_FILE}")"
AWS_SECRET_ACCESS_KEY="$(<"${AWS_SECRET_ACCESS_KEY_FILE}")"

backup_dir=/var/backups/postgres
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
dump_file="${backup_dir}/${POSTGRES_DB}-${timestamp}.dump"

cleanup() {
    rm -f "${dump_file}"
}
trap cleanup EXIT

mkdir -p "${backup_dir}"

pg_dump \
    --host="${POSTGRES_HOST}" \
    --port="${POSTGRES_PORT:-5432}" \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --format=custom \
    --compress=9 \
    --no-owner \
    --file="${dump_file}"

if ! restic snapshots --json >/dev/null 2>&1; then
    restic init
fi

restic backup \
    --tag postgres \
    --tag "database:${POSTGRES_DB}" \
    "${dump_file}"

restic forget \
    --tag postgres \
    --keep-daily "${BACKUP_KEEP_DAILY:-7}" \
    --keep-weekly "${BACKUP_KEEP_WEEKLY:-4}" \
    --keep-monthly "${BACKUP_KEEP_MONTHLY:-12}" \
    --prune

restic check --read-data-subset=5%

printf '{"level":"info","event":"postgres_backup_completed","database":"%s","timestamp":"%s"}\n' \
    "${POSTGRES_DB}" "${timestamp}"
