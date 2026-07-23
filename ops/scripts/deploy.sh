#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <image> <immutable-tag>" >&2
    exit 64
fi

export APP_IMAGE="$1"
export APP_IMAGE_TAG="$2"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
cd "${repo_root}"

env_value() {
    local key="$1"
    [[ -f .env ]] || return 0
    sed -n -E "s/^${key}=//p" .env | tail -n 1
}

app_host="${APP_HOST:-$(env_value APP_HOST)}"
backup_enabled="${BACKUP_ENABLED:-$(env_value BACKUP_ENABLED)}"

if [[ -z "${app_host}" ]]; then
    echo "APP_HOST must be exported or present in .env" >&2
    exit 64
fi

mkdir -p .deploy ops/traefik/dynamic

active_file=.deploy/active-slot
if [[ -f "${active_file}" ]]; then
    active_slot="$(<"${active_file}")"
    case "${active_slot}" in
        blue) target_slot=green ;;
        green) target_slot=blue ;;
        *) echo "Invalid active slot: ${active_slot}" >&2; exit 65 ;;
    esac
    has_active=true
else
    active_slot=""
    target_slot=blue
    has_active=false
fi

if [[ "${has_active}" == false ]]; then
    APP_HOST="${app_host}" "${script_dir}/render-traefik-config.sh" "${target_slot}"
fi

base_services=(traefik postgres qdrant)
if [[ "${backup_enabled:-false}" == "true" ]]; then
    base_services+=(backup)
fi

docker compose up \
    --detach \
    --remove-orphans \
    --wait \
    --wait-timeout "${PLATFORM_WAIT_TIMEOUT_SECONDS:-180}" \
    "${base_services[@]}"
docker compose pull "app-${target_slot}"
docker compose up --detach --no-deps --no-build "app-${target_slot}"

container_id="$(docker compose ps --quiet "app-${target_slot}")"
if [[ -z "${container_id}" ]]; then
    echo "Target container app-${target_slot} was not created" >&2
    exit 70
fi

healthy=false
for _ in $(seq 1 60); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
    if [[ "${status}" == healthy ]]; then
        healthy=true
        break
    fi
    if [[ "${status}" == unhealthy || "${status}" == exited || "${status}" == dead ]]; then
        break
    fi
    sleep 2
done

if [[ "${healthy}" != true ]]; then
    docker compose logs --tail=200 "app-${target_slot}" >&2
    docker compose rm --force --stop "app-${target_slot}" >/dev/null
    echo "Target app-${target_slot} did not become healthy" >&2
    exit 70
fi

APP_HOST="${app_host}" "${script_dir}/render-traefik-config.sh" "${target_slot}"

healthcheck_url="${DEPLOY_HEALTHCHECK_URL:-$(env_value DEPLOY_HEALTHCHECK_URL)}"
healthcheck_url="${healthcheck_url:-https://${app_host}/_stcore/health}"

public_healthy=false
for _ in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 10 "${healthcheck_url}" >/dev/null; then
        public_healthy=true
        break
    fi
    sleep 2
done

if [[ "${public_healthy}" != true ]]; then
    if [[ "${has_active}" == true ]]; then
        APP_HOST="${app_host}" "${script_dir}/render-traefik-config.sh" "${active_slot}"
        docker compose rm --force --stop "app-${target_slot}" >/dev/null
    fi
    echo "Public health check failed: ${healthcheck_url}" >&2
    exit 70
fi

printf '%s\n' "${target_slot}" >"${active_file}"

if [[ "${has_active}" == true ]]; then
    sleep "${DEPLOY_DRAIN_SECONDS:-15}"
    docker compose rm --force --stop "app-${active_slot}" >/dev/null
fi

docker image prune --force --filter 'until=168h' >/dev/null
printf 'Deployment complete: %s:%s is active on %s.\n' \
    "${APP_IMAGE}" "${APP_IMAGE_TAG}" "${target_slot}"
