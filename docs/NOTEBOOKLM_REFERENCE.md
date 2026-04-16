# Obsidian Legion — Reference Document for NotebookLM

Upload this file (plus README.md and INSTALL_ME.md) to Google NotebookLM to create an interactive knowledge base about Obsidian Legion.

---

## What is Obsidian Legion?

Obsidian Legion is an open-source, vault-native task engine and LLM-powered wiki compiler for Obsidian vaults. It gives multiple AI agents (Claude Code, Codex, Gemini CLI, Ollama) the same verbs against the same Markdown files, eliminating coordination sludge.

In v0.2.0, it added the Karpathy LLM Wiki pattern — a "compile, don't retrieve" alternative to traditional RAG where an LLM reads raw documents once and writes structured, wikilinked encyclopedia articles.

## Core Concepts

### 3-Layer Memory Architecture

**Layer 1: Obsidian CLI + Legion**
Direct vault access. Tasks are Markdown files with YAML frontmatter. Every agent shares the same contract. Dashboards regenerate as Markdown. Fastest, cheapest, no model needed.

**Layer 2: LLM Wiki (Karpathy Pattern)**
An LLM reads raw source documents and compiles them into structured wiki articles with titles, summaries, tags, and [[wikilinks]]. The key insight: traditional RAG is stateless (re-discovers knowledge every query). The wiki compiler does heavy work ONCE and produces persistent, navigable knowledge.

**Layer 3: Qdrant Vector Search**
Semantic fallback for when Layers 1 and 2 are insufficient. A sync script walks the vault, generates embeddings via Ollama, and upserts to Qdrant. Queried via the --deep flag.

### Task Engine

Every agent follows the same loop: next → claim → work → done → refresh.

Tasks are canonical Markdown with YAML frontmatter: task_id, title, summary, status, priority, assignee, project, area, lane, effort, due date, acceptance criteria, and an append-only log.

Supported agents: Claude Code, Codex, Gemini CLI, Ollama, humans via Obsidian UI.

### Wiki Compiler

The wiki compiler supports two tiers:
- **Heavy** (default): 150-300 word articles with Summary, Key Details, and Related Concepts sections. Uses larger models (qwen3.5:27b or cloud models).
- **Light**: 50-100 word articles with key facts only. Uses smaller models (llama3.2:3b) for fast maintenance.

Four specialized prompt templates: entity (people/orgs), concept (abstract ideas), event (historical moments), source (reference cards).

### MCP Integration

8 MCP tools exposed via FastMCP: wiki_bootstrap, wiki_ingest, wiki_compile, wiki_compile_vault, wiki_search, wiki_status, wiki_list, plus all task engine tools (capture_task, list_tasks, next_tasks, claim_task, complete_task, refresh_dashboards).

## CLI Reference

### Task Commands
- `bootstrap` — Create directory structure
- `capture` — Create a new task
- `list` — Query tasks by status/assignee/project
- `next` — Show highest-priority actionable tasks
- `claim` — Assign yourself to a task
- `update` — Patch any task field
- `done` — Mark task completed
- `refresh` — Rebuild dashboards
- `doctor` — Health check

### Wiki Commands
- `wiki bootstrap` — Create wiki/ and raw/ directories
- `wiki compile` — Compile new/changed raw files (supports --vault-wide, --tier, --model, --dry-run)
- `wiki ingest <path>` — Ingest a specific file
- `wiki search <query>` — Search wiki articles (supports --deep for Qdrant fallback)
- `wiki status` — Show compilation statistics
- `wiki list` — List all articles (supports --type filter)
- `wiki get <id>` — Show a specific article

## Installation

Three options:
1. **Give INSTALL_ME.md to your LLM** — The LLM reads instructions and sets everything up
2. **Run install.sh** — Checks prerequisites, creates venv, installs deps, pulls model
3. **Manual** — git clone, pip install -e ".[all]", ollama pull llama3.2:3b

Prerequisites: Python 3.11+, Ollama (for wiki compilation).

## Technical Stack

- Python 3.11+ with dataclasses and type hints
- PyYAML for frontmatter parsing
- httpx for Ollama API calls
- qdrant-client (optional) for Layer 3
- FastMCP for MCP server
- pytest for testing (18 tests with MockCompiler)

## The Karpathy Pattern

Based on Andrej Karpathy's LLM Wiki gist. Instead of:
1. Chunk documents → embed → store in vector DB → query at runtime (traditional RAG)

The wiki pattern does:
1. Read raw document → LLM extracts entities/concepts → writes structured articles → stores as Markdown

The result: persistent, navigable, human-readable knowledge that any agent can browse without vector search. Vector search exists as Layer 3 fallback, not the primary path.

## Project Links

- GitHub: github.com/valx-vex/obsidian-legion
- License: Apache 2.0
- Built by: VALX VEX (one human + multiple AI agents)
