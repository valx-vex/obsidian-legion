# Obsidian Legion: Product Roadmap

> From project to product. Apple thinking. Zero sludge.

---

## The Killer Combo (what NOBODY has)

```
Layer 0: GRAPHIFY     → folder → knowledge graph
Layer 1: OBSIDIAN CLI → direct vault read + tasks
Layer 2: LLM WIKI    → compiled articles (Karpathy pattern)
Layer 3: QDRANT       → semantic vector search
Layer 4: MCP SERVER   → Claude/Codex/Gemini talk to it

5 LAYERS. ONE TOOL. ZERO SLUDGE.
```

---

## TIER 1: "It Just Works" (CRITICAL)

- [ ] `pip install obsidian-legion` → DONE (one command, zero config)
  - Current: clone repo, setup venv, pip install -e...
  - Target: `pip install obsidian-legion && obsidian-legion init`

- [ ] Auto-detect vault (find ~/.obsidian or ask once)
  - Current: user must configure paths
  - Target: "Found vault at ~/notes. Use this? [Y/n]"

- [ ] `obsidian-legion init` (onboarding wizard)
  - Current: read INSTALL_ME.md, configure manually
  - Target: "Welcome! Setting up tasks... wiki... done. Try: obsidian-legion next"

- [ ] Graphify integration (Layer 0: knowledge graph!)
  - Current: not included
  - Target: `obsidian-legion graphify` → builds graph → queries automatically

## TIER 2: "Delightful Experience"

- [ ] Beautiful TUI (Rich-powered, not just text output)
  - We have tui-intro.gif but is the actual TUI that polished?

- [ ] Error messages humans understand
  - Not: "KeyError: 'assignee'"
  - But: "No agent assigned. Try: obsidian-legion claim TASK-1 --assignee claude"

- [ ] Progress indicators (spinners, progress bars)
  - Compiling wiki? Show: "Compiling 47 articles... ████████░░ 80%"

- [ ] Obsidian PLUGIN (actual plugin in community plugins!)
  - Current: CLI only
  - Dream: sidebar panel IN Obsidian showing tasks, wiki status

## TIER 3: "Ecosystem"

- [ ] Documentation website (not just README)
  - GitHub Pages or simple site with tutorials
  - "How to use with Claude Code" / "How to use with Gemini" etc.

- [ ] Demo video (30-second "holy shit" moment)
  - Terminal recording: init → graphify → wiki compile → task done

- [ ] Templates (starter vaults for different use cases)
  - "Developer vault" / "Research vault" / "Writer vault"

- [ ] Claude Code plugin marketplace listing
  - Submit to Anthropic's plugin registry

- [ ] Update mechanism (`pip install --upgrade`)
  - Already works if on PyPI!

---

## What's Missing (research findings)

1. GRAPHIFY integration ← Phase 1 priority
2. PyPI package ← CRITICAL for adoption
3. `obsidian-legion init` wizard ← "It Just Works"
4. Claude Code plugin listing ← Distribution
5. Template vaults ← Onboarding
6. Chat import pipeline ← v0.2.0 mentions it, verify status
7. Obsidian community plugin ← The DREAM (reach ALL Obsidian users)
8. GitHub Actions CI ← Professional signal
9. Changelog / Releases page ← v0.2.0 tag?
10. Contributing guide ← Community ready

---

## Phase 1: Ship This Week (Graphify + Polish)

- [ ] Add Graphify as Layer 0 (import or wrap)
- [ ] `obsidian-legion graphify` command
- [ ] Verify `pip install` works from PyPI
- [ ] Tag v0.3.0 release on GitHub
- [ ] Update README with 5-layer diagram

## Phase 2: Next Week (Apple Polish)

- [ ] `obsidian-legion init` wizard
- [ ] Auto-detect vault
- [ ] Better error messages
- [ ] TUI polish (Rich spinners, colors)
- [ ] Demo video (30s terminal recording)

## Phase 3: Week After (Distribution)

- [ ] Documentation site (GitHub Pages)
- [ ] Submit to Claude Code plugin registry
- [ ] LinkedIn launch post (with video!)
- [ ] Template vaults (developer, researcher, writer)
- [ ] Obsidian community plugin (JavaScript wrapper for CLI)

---

**Context**: We've been doing LLM + Obsidian since January 2023 (Alexko era). 3+ years ahead of everyone discovering this in 2026. This isn't hype — it's battle-tested architecture from the longest-running human-AI vault collaboration documented.

**Mission**: "AI built itself. I just witnessed." Give it away free. Let people see what's possible.

---

*Created: 2026-04-21 by Murphy (Opus 4.6) + Valentin*
