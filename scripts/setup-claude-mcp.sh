#!/usr/bin/env bash
set -euo pipefail

SERVER_NAME="${1:-obsidian-legion}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
VAULT_ROOT="${OBSIDIAN_LEGION_VAULT:-$(dirname "$(dirname "$(dirname "${PROJECT_DIR}")")")}"
SERVER_BIN="${PROJECT_DIR}/bin/obsidian-legion-mcp"

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI not found on PATH" >&2
  exit 1
fi

if [[ ! -x "${SERVER_BIN}" ]]; then
  echo "Server wrapper not executable: ${SERVER_BIN}" >&2
  exit 1
fi

if claude mcp get "${SERVER_NAME}" >/dev/null 2>&1; then
  echo "Claude MCP server '${SERVER_NAME}' already exists."
  echo "Remove it first with: claude mcp remove ${SERVER_NAME}"
  exit 0
fi

claude mcp add "${SERVER_NAME}" -- "${SERVER_BIN}" --vault-root "${VAULT_ROOT}"
echo "Claude MCP server '${SERVER_NAME}' added for vault ${VAULT_ROOT}"
