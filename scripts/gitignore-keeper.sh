#!/usr/bin/env bash
# gitignore-keeper.sh
# -----------------------------------------------------------------------------
# Long-running watchdog that keeps /app/.gitignore free of platform-injected
# `.env` and `.pack` blocks. The Emergent platform hook re-adds these on pod
# restarts and at unpredictable intervals during dev — causing deploy
# pipeline failures at the "fetch envs" step.
#
# Strategy: run `predeploy.sh` in a loop, 60s apart, indefinitely. predeploy.sh
# is idempotent (no-op when the file is clean), so this is cheap.
#
# Managed by supervisor — see /etc/supervisor/conf.d/supervisord_gitignore_keeper.conf
# -----------------------------------------------------------------------------
set -u

INTERVAL_SECS="${GITIGNORE_KEEPER_INTERVAL:-60}"

echo "[gitignore-keeper] starting — interval=${INTERVAL_SECS}s"

while true; do
  if ! bash /app/predeploy.sh; then
    echo "[gitignore-keeper] predeploy.sh exited non-zero — continuing anyway" >&2
  fi
  sleep "${INTERVAL_SECS}"
done
