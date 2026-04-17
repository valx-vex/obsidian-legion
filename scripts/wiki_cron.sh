#!/bin/bash
# Wiki auto-compile cron job.
#
# Runs obsidian-legion wiki compile in light tier mode, logging output
# to /tmp/obsidian-legion-wiki-cron.log.
#
# Install:
#   crontab -e
#   */30 * * * * /path/to/obsidian-legion/scripts/wiki_cron.sh /path/to/vault
#
# Usage:
#   ./scripts/wiki_cron.sh [vault-root]

set -euo pipefail

VAULT_ROOT="${1:-$HOME/my-vault}"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/obsidian-legion-wiki-cron.log"

cd "$SCRIPT_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || true

echo "[$(date -Iseconds)] Wiki cron starting..." >> "$LOG"
obsidian-legion wiki compile --vault-root "$VAULT_ROOT" --tier light >> "$LOG" 2>&1
echo "[$(date -Iseconds)] Wiki cron complete." >> "$LOG"
