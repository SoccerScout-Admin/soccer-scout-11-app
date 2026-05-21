#!/usr/bin/env bash
# predeploy.sh
# -----------------------------------------------------------------------------
# Strip platform-injected `.env` ignore patterns from /app/.gitignore before
# deploys. The Emergent platform hook re-adds these on pod restarts, which
# causes the deployment pipeline to fail at the "fetch envs" step because the
# .env files are ignored and never reach the build container.
#
# Run manually before clicking Deploy:
#     bash /app/predeploy.sh
#
# Or hook this into your deploy workflow. It is idempotent and safe to run
# repeatedly.
# -----------------------------------------------------------------------------
set -euo pipefail

GITIGNORE="/app/.gitignore"

if [[ ! -f "${GITIGNORE}" ]]; then
  echo "[predeploy] ERROR: ${GITIGNORE} not found." >&2
  exit 1
fi

echo "[predeploy] Scanning ${GITIGNORE} for injected .env ignore patterns..."

# Patterns the platform hook keeps injecting at the bottom of .gitignore.
# Each pattern is matched as a *whole line* (no leading whitespace).
PATTERNS=(
  '^\.env$'
  '^\.env\.\*$'
  '^\*\.env$'
  '^-e$'
  '^# Environment and credential files$'
  '^frontend/node_modules/\.cache/default-development/[0-9]+\.pack$'
)

REMOVED_TOTAL=0
TMP_FILE="$(mktemp)"
cp "${GITIGNORE}" "${TMP_FILE}"

for pat in "${PATTERNS[@]}"; do
  COUNT_BEFORE=$(grep -cE "${pat}" "${TMP_FILE}" || true)
  if [[ "${COUNT_BEFORE}" -gt 0 ]]; then
    echo "[predeploy] Removing ${COUNT_BEFORE} line(s) matching: ${pat}"
    grep -vE "${pat}" "${TMP_FILE}" > "${TMP_FILE}.new" || true
    mv "${TMP_FILE}.new" "${TMP_FILE}"
    REMOVED_TOTAL=$((REMOVED_TOTAL + COUNT_BEFORE))
  fi
done

# Collapse trailing blank lines so the file ends cleanly with a single newline.
awk 'BEGIN{blank=0} { if ($0 ~ /^$/) { blank++ } else { for(i=0;i<blank;i++) print ""; blank=0; print } } END { print "" }' "${TMP_FILE}" > "${TMP_FILE}.clean"
mv "${TMP_FILE}.clean" "${TMP_FILE}"

if [[ "${REMOVED_TOTAL}" -eq 0 ]]; then
  echo "[predeploy] .gitignore is clean. No injected patterns found."
  rm -f "${TMP_FILE}"
  exit 0
fi

mv "${TMP_FILE}" "${GITIGNORE}"
echo "[predeploy] Removed ${REMOVED_TOTAL} injected line(s) from .gitignore."
echo "[predeploy] Done. Safe to deploy."
