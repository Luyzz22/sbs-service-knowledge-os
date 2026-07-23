#!/usr/bin/env sh
set -eu

export_secret() {
    variable_name="$1"
    file_variable_name="${variable_name}_FILE"
    eval "file_path=\${${file_variable_name}:-}"

    if [ -n "${file_path}" ]; then
        if [ ! -r "${file_path}" ]; then
            echo "Secret file for ${variable_name} is not readable: ${file_path}" >&2
            exit 1
        fi
        value="$(cat "${file_path}")"
        export "${variable_name}=${value}"
        unset "${file_variable_name}"
    fi
}

export_secret OPENAI_API_KEY
export_secret LLAMA_CLOUD_API_KEY

exec "$@"
