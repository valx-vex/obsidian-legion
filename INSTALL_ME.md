# Give This File to Your LLM

You are helping a user install and set up Obsidian Legion with the LLM Wiki feature.

## Prerequisites Check

Run these commands and report what's missing:

```bash
python3 --version    # Need 3.11+
ollama --version     # Need Ollama installed
ollama list          # Check available models
```

If Python < 3.11: tell the user to install Python 3.11+ from python.org or via brew.
If Ollama missing: tell the user to install from https://ollama.com/download.

## Installation

```bash
# Clone the repo
git clone https://github.com/valx-vex/obsidian-legion.git
cd obsidian-legion

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"

# Pull a local model for wiki compilation
ollama pull llama3.2:3b
```

## Setup for the User's Vault

Ask the user: "Where is your Obsidian vault? (e.g., ~/my-vault, ~/Documents/notes)"

Then run:

```bash
# Bootstrap the wiki system (creates wiki/ and raw/ directories)
./bin/obsidian-legion wiki bootstrap --vault-root <VAULT_PATH>
```

This creates:
- `<VAULT>/wiki/` -- where compiled articles live
- `<VAULT>/raw/` -- where source files go for compilation
- `<VAULT>/wiki/index.md` -- auto-generated content catalog

## First Compilation

Help the user add a test file:

```bash
# Create a test raw file
cat > <VAULT_PATH>/raw/test-article.md << 'EOF'
# My First Article

Write some notes here about any topic. The LLM will extract entities,
concepts, and themes and compile them into structured wiki articles.

This can be anything: meeting notes, research findings, book highlights,
project documentation, or personal knowledge.
EOF

# Compile it
./bin/obsidian-legion wiki compile --vault-root <VAULT_PATH>

# Check results
./bin/obsidian-legion wiki status --vault-root <VAULT_PATH>
cat <VAULT_PATH>/wiki/index.md
```

## Vault-Wide Compilation

To compile articles from the ENTIRE vault (not just raw/):

```bash
./bin/obsidian-legion wiki compile --vault-wide --vault-root <VAULT_PATH>
```

This scans all .md files in the vault (excluding wiki/, .obsidian/, .git/) and compiles new/changed files into wiki articles.

## Using Bigger Models

For richer articles, use a larger model:

```bash
# Local large model
ollama pull qwen3.5:27b
./bin/obsidian-legion wiki compile --model qwen3.5:27b --vault-root <VAULT_PATH>

# Or use Ollama Cloud models (no download needed)
./bin/obsidian-legion wiki compile --model qwen3.5:397b-cloud --vault-root <VAULT_PATH>

# Light mode (fast, small articles)
./bin/obsidian-legion wiki compile --tier light --vault-root <VAULT_PATH>

# Heavy mode (detailed, encyclopedia-style)
./bin/obsidian-legion wiki compile --tier heavy --vault-root <VAULT_PATH>
```

## Task Engine (Original Feature)

Obsidian Legion also includes a multi-agent task engine:

```bash
# Create a task
./bin/obsidian-legion capture "My task title" --summary "What needs to be done" --vault-root <VAULT_PATH>

# See your tasks
./bin/obsidian-legion next --vault-root <VAULT_PATH>

# Complete a task
./bin/obsidian-legion done TASK-20260416-001 --vault-root <VAULT_PATH>
```

## MCP Integration (for Claude Code / Gemini CLI)

```bash
# Register with Claude Code
./scripts/setup-claude-mcp.sh

# Register with Gemini CLI
./scripts/setup-gemini-mcp.sh
```

This gives your AI agent direct access to wiki and task tools.

## Troubleshooting

- **"Ollama not found"**: Install from https://ollama.com/download
- **"Model not found"**: Run `ollama pull llama3.2:3b`
- **Compilation timeout**: Use a smaller model or add `--tier light`
- **JSON parse errors**: The LLM output couldn't be parsed. Try a different model.
- **"Does not look like an Obsidian vault"**: The vault needs a `.obsidian/` directory and `06-daily/action-points/` directory. Run `mkdir -p <VAULT>/.obsidian <VAULT>/06-daily/action-points` to create them.
