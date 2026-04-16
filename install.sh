#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "  Obsidian Legion Installer"
echo "  One contract. Every agent. Zero sludge."
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok() { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[!]${NC} $1"; }
fail() { echo -e "  ${RED}[X]${NC} $1"; }

# Check Python
echo "Checking prerequisites..."
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        ok "Python $PY_VERSION"
    else
        fail "Python $PY_VERSION (need 3.11+)"
        echo "    Install: https://python.org or 'brew install python@3.11'"
        exit 1
    fi
else
    fail "Python not found"
    echo "    Install: https://python.org or 'brew install python@3.11'"
    exit 1
fi

# Check Ollama
if command -v ollama &>/dev/null; then
    ok "Ollama installed"
    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        ok "Ollama running"
    else
        warn "Ollama installed but not running. Start it: 'ollama serve'"
    fi
else
    warn "Ollama not installed (needed for wiki compilation)"
    echo "    Install: https://ollama.com/download"
fi

# Check if we're in the repo
if [ ! -f "pyproject.toml" ]; then
    fail "Run this from the obsidian-legion directory"
    echo "    cd obsidian-legion && bash install.sh"
    exit 1
fi

echo ""
echo "Installing Obsidian Legion..."

# Create venv if needed
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    ok "Created virtual environment"
else
    ok "Virtual environment exists"
fi

# Activate and install
source .venv/bin/activate
pip install -e ".[all]" -q 2>&1 | tail -1
ok "Installed obsidian-legion with all dependencies"

# Pull default model
if command -v ollama &>/dev/null; then
    if ! ollama list 2>/dev/null | grep -q "llama3.2:3b"; then
        echo "  Pulling default model (llama3.2:3b)..."
        ollama pull llama3.2:3b
        ok "Model llama3.2:3b ready"
    else
        ok "Model llama3.2:3b already available"
    fi
fi

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Next steps:"
echo ""
echo "  # Activate the environment"
echo "  source .venv/bin/activate"
echo ""
echo "  # Bootstrap wiki in your vault"
echo "  ./bin/obsidian-legion wiki bootstrap --vault-root ~/your-vault"
echo ""
echo "  # Add files to ~/your-vault/raw/ then compile"
echo "  ./bin/obsidian-legion wiki compile --vault-root ~/your-vault"
echo ""
echo "  # Or compile from your entire vault"
echo "  ./bin/obsidian-legion wiki compile --vault-wide --vault-root ~/your-vault"
echo ""
echo "  # See INSTALL_ME.md for the full guide (or give it to your LLM!)"
echo ""
