#!/usr/bin/env bash
set -Eeuo pipefail

slot="${1:-}"
case "${slot}" in
    blue|green) ;;
    *) echo "Usage: $0 <blue|green>" >&2; exit 64 ;;
esac

if [[ -z "${APP_HOST:-}" ]]; then
    echo "APP_HOST is required" >&2
    exit 64
fi

if [[ ! "${APP_HOST}" =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo "APP_HOST contains invalid characters" >&2
    exit 64
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
template="${repo_root}/ops/traefik/app.yml.template"
output_dir="${repo_root}/ops/traefik/dynamic"
output="${output_dir}/app.yml"

mkdir -p "${output_dir}"
temporary="$(mktemp "${output_dir}/app.yml.XXXXXX")"
trap 'rm -f "${temporary}"' EXIT

sed \
    -e "s/__APP_HOST__/${APP_HOST}/g" \
    -e "s/__APP_TARGET__/app-${slot}/g" \
    "${template}" >"${temporary}"

chmod 0644 "${temporary}"
mv -f "${temporary}" "${output}"
trap - EXIT

printf 'Traefik now routes %s to app-%s.\n' "${APP_HOST}" "${slot}"
