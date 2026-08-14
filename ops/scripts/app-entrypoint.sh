#!/usr/bin/env sh
set -eu

# Application configuration reads Docker/Kubernetes secret files directly via
# the *_FILE convention. Do not copy secret values into the process environment.
umask 077

exec "$@"
