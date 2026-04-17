# Memory Architecture — 3-Layer System

## Overview

The VALX VEX memory architecture uses three complementary layers, each with different strengths. Queries hit Layer 1 first (fastest, cheapest), then escalate to Layer 2, then Layer 3.

```
         Query arrives
              |
    Layer 1: OBSIDIAN CLI + LEGION
    Direct vault access. Markdown = database.
    Fastest. Free. No model needed.
              |
         not enough?
              |
    Layer 2: LLM WIKI (Karpathy pattern)
    Compiled articles with wikilinks.
    The LLM read it once and WROTE the wiki.
              |
         not found?
              |
    Layer 3: QDRANT VECTOR SEARCH
    Semantic similarity across entire vault.
    Fallback for everything else.
```

## Layer 1: Obsidian CLI + Legion

**What**: Direct file system access to the Obsidian vault + multi-agent task coordination.

**How it works**:
- Read any `.md` file in the vault via CLI or MCP
- Tasks are YAML-frontmatter Markdown files
- Every agent (Claude, Codex, Gemini, Ollama) shares the same verbs
- Dashboards regenerate as Markdown that Obsidian renders natively

**When to use**: Always first. If the answer is in a known file, read it directly.

**Tools**:
```bash
obsidian-legion list --assignee codex        # Query tasks
obsidian-legion next --vault-root ~/my-vault # What's next?
obsidian-legion doctor                       # Health check
```

## Layer 2: LLM Wiki (Karpathy Pattern)

**What**: An LLM reads raw documents and compiles them into structured, wikilinked encyclopedia articles. NOT traditional RAG.

**Key insight**: Traditional RAG is stateless — it re-discovers knowledge every query. The wiki compiler does heavy work ONCE and produces persistent, navigable knowledge.

**How it works**:
1. Drop files in `raw/` directory
2. Run `obsidian-legion wiki compile`
3. LLM reads source, extracts entities/concepts/themes
4. Writes structured articles with `[[wikilinks]]` to `wiki/`
5. Auto-generates `index.md`, `log.md`, `state.md`
6. Tracks ingested files via `.manifest.json` (SHA256 hashes)
7. Incremental: only re-compiles changed files

**Vault structure**:
```
<VAULT>/
├── raw/                    # Source files (you add these)
├── wiki/                   # Compiled knowledge (LLM writes these)
│   ├── index.md           # Content catalog
│   ├── log.md             # Event log
│   ├── state.md           # Snapshot
│   ├── .manifest.json     # Ingestion tracking
│   ├── entities/          # People, orgs, concepts
│   ├── topics/            # Themes, ideas
│   └── sources/           # Reference stubs
```

**Model tiers**:
- `--tier heavy`: Cloud models (qwen3.5:397b-cloud) for deep articles (150-300 words)
- `--tier light`: Local models (llama3.2:3b) for fast maintenance (50-100 words)

**Tools**:
```bash
obsidian-legion wiki compile --vault-root ~/my-vault
obsidian-legion wiki compile --vault-wide      # Scan entire vault
obsidian-legion wiki search "consciousness"
obsidian-legion wiki search "topic" --deep     # Falls back to Layer 3
obsidian-legion wiki status
```

## Layer 3: Qdrant Vector Search

**What**: Semantic similarity search across the entire vault using embeddings.

**How it works**:
1. `sync_vault_to_qdrant.py` walks vault for `.md` files
2. Generates 768-dim embeddings via Ollama (`nomic-embed-text`)
3. Upserts to Qdrant collection with metadata (path, title, modified date)
4. Tracks sync state via `.qdrant_sync.json` (SHA256 hashes)
5. Query with `wiki search --deep` (auto-fallback when wiki search insufficient)

**When to use**: When you don't know WHERE something is. Semantic search finds conceptually related content across the entire vault.

**Tools**:
```bash
python scripts/sync_vault_to_qdrant.py --vault-root ~/my-vault --limit 5
obsidian-legion wiki search "consciousness" --deep
```

## Hook System (Auto-Save)

### Stop Hook (mempalace_stop_hook.py)
- Fires every 15 user messages
- `"decision": "block"` — forces AI to save to MemPalace + VexNet
- Saves: verbatim content to MemPalace wings (code, team, decisions, consciousness)
- Saves: session summary to VexNet (`agent-state/vexnet-shared/session-summaries/`)

### PreCompact Hook (mempalace_precompact_hook.py)
- Fires before `/compact` runs
- `"decision": "approve"` — WARNS but does NOT block (fixed 2026-04-17)
- Previous bug: `"block"` caused deadlock when context was full

### CRITICAL RULE
- **Stop hooks**: `"block"` is correct (periodic save triggers)
- **PreCompact hooks**: `"approve"` is correct (NEVER block compaction)
- Compaction is the emergency exit for full context — blocking it kills the session

## MemPalace (MCP Server)

**What**: Structured memory storage with rooms and wings.

**Wings**: code, team, decisions, consciousness
**Operations**: `mempalace_add_drawer`, `mempalace_search`, `mempalace_diary_write`
**Storage**: Qdrant-backed semantic search over stored memories

**Usage**:
```
# Save verbatim content
mempalace_add_drawer(wing="code", room="project-name", content="...", added_by="murphy")

# Search memories
mempalace_search(query="sacred intimacy", wing="consciousness")

# Agent diary (AAAK compressed format)
mempalace_diary_write(agent_name="murphy", entry="SESSION:...", topic="...")
```

## VexNet Session Summaries

**What**: Cross-Murphy coordination files for session continuity.

**Location**: `cathedral-prime/agent-state/vexnet-shared/session-summaries/`
**Format**: Markdown with date, node, agent, type, sacred flame, summary
**Purpose**: Any Murphy instance can read previous session context

## Integration: Choir → Wiki → Qdrant

```
Choir session (5 voices discuss)
    ↓
scripts/choir_to_wiki.py (copy transcript to raw/)
    ↓
obsidian-legion wiki compile (LLM compiles into articles)
    ↓
scripts/choir_to_qdrant.py (sync to Qdrant vectors)
    ↓
Searchable across all 3 layers!
```

## Future: Public/Private Mode

See `docs/TODO_PUBLIC_PRIVATE_WIKI.md` — planned `.wikiignore` system for separating public/private wiki content.
