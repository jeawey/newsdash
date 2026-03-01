#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  cat <<'USAGE'
Usage:
  bash scripts/log_entry.sh <worklog|changelog> "<title>" "<details>"

Examples:
  bash scripts/log_entry.sh worklog "Worker restart" "worker neu gestartet, health geprüft"
  bash scripts/log_entry.sh changelog "Lock fix" "Datei-Lock ergänzt, stale cleanup verbessert"
USAGE
  exit 1
fi

KIND="$1"
TITLE="$2"
DETAILS="${3:-}"

TS="$(TZ=Europe/Madrid date '+%Y-%m-%d %H:%M:%S Europe/Madrid')"
HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
STATUS="$(git status --short 2>/dev/null || true)"

case "$KIND" in
  worklog)
    FILE="docs/WORKLOG.md"
    {
      echo
      echo "## ${TS} | step"
      echo "- actor: $(whoami)"
      echo "- environment: local"
      echo "- summary: ${TITLE}"
      echo "- result: pending"
      if [[ -n "$DETAILS" ]]; then
        echo "- notes: ${DETAILS}"
      fi
      echo "- git_head: ${HEAD}"
      echo "- git_status:"
      echo '```text'
      if [[ -n "$STATUS" ]]; then
        echo "$STATUS"
      else
        echo "(clean)"
      fi
      echo '```'
    } >> "$FILE"
    ;;
  changelog)
    FILE="docs/CHANGELOG.md"
    {
      echo
      echo "### ${TS} | ${TITLE}"
      echo "- Details: ${DETAILS:-n/a}"
      echo "- Commit: ${HEAD}"
    } >> "$FILE"
    ;;
  *)
    echo "Unknown kind: ${KIND}. Use 'worklog' or 'changelog'."
    exit 1
    ;;
esac

echo "Logged to ${FILE}"
