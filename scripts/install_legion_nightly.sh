#!/bin/bash
# Install the com.vex.legion.nightly launchd agent (R5 §4.6).
# Preview without installing: scripts/install_legion_nightly.sh --render-only
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.vex.legion.nightly"
TEMPLATE="$REPO_ROOT/scripts/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/.vex/logs/legion"
PYTHON="${LEGION_NIGHTLY_PYTHON:-$REPO_ROOT/.venv/bin/python}"
SCRIPT="$REPO_ROOT/scripts/legion_nightly.py"

[ -f "$TEMPLATE" ] || { echo "template not found: $TEMPLATE" >&2; exit 1; }
[ -f "$SCRIPT" ] || { echo "orchestrator not found: $SCRIPT" >&2; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__SCRIPT__|$SCRIPT|g" \
    -e "s|__REPO__|$REPO_ROOT|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$TEMPLATE" > "$TMP"
plutil -lint "$TMP" >/dev/null

if [ "${1:-}" = "--render-only" ]; then
    cat "$TMP"
    exit 0
fi

[ -x "$PYTHON" ] || { echo "python not found/executable: $PYTHON" >&2; exit 1; }
mkdir -p "$LOG_DIR"
cp "$TMP" "$DEST"

UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST" || true
launchctl kickstart "gui/$UID_NUM/$LABEL" || true
echo "installed $LABEL — nightly 05:15."
echo "  force a run: launchctl kickstart -k gui/$UID_NUM/$LABEL"
echo "  logs: $LOG_DIR/nightly.{out,err}.log"
