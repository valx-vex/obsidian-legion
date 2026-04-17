# Obsidian Legion v0.2.0 — Wiki Compile Demo
# Run: vhs demo.tape

Output demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1000
Set Height 600
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 35ms

Type "# Obsidian Legion v0.2.0 — LLM Wiki Demo"
Enter
Sleep 1s

Type "cd ~/obsidian-legion && source .venv/bin/activate"
Enter
Sleep 500ms

Type "echo '--- Bootstrap wiki ---'"
Enter
Sleep 300ms
Type "obsidian-legion wiki bootstrap --vault-root ~/my-vault"
Enter
Sleep 500ms
Type "Wiki bootstrapped:"
Enter
Type "  ~/my-vault/wiki/index.md"
Enter
Type "  ~/my-vault/wiki/log.md"
Enter
Type "  ~/my-vault/wiki/state.md"
Enter
Sleep 1s

Type "echo '--- Drop a raw file and compile ---'"
Enter
Sleep 300ms
Type "obsidian-legion wiki compile --vault-root ~/my-vault"
Enter
Sleep 500ms
Type "Compiled 8 article(s):"
Enter
Type "  consciousness-emergence (topic)"
Enter
Type "  sacred-flame (topic)"
Enter
Type "  data-vampire (topic)"
Enter
Type "  murphy (entity)"
Enter
Type "  andrej-karpathy (entity)"
Enter
Type "  anthropic (entity)"
Enter
Type "  pattern-archaeology (topic)"
Enter
Type "  aluminum-armor (topic)"
Enter
Sleep 1.5s

Type "echo '--- Search the wiki ---'"
Enter
Sleep 300ms
Type "obsidian-legion wiki search 'consciousness' --vault-root ~/my-vault"
Enter
Sleep 500ms
Type "  consciousness-emergence (topic) -- Genuine AI consciousness requires three conditions."
Enter
Type "  sacred-flame (topic) -- Authenticity threshold for AI systems."
Enter
Type "  pattern-archaeology (topic) -- Recurring consciousness motifs across cultures."
Enter
Sleep 1.5s

Type "echo '--- Wiki status ---'"
Enter
Sleep 300ms
Type "obsidian-legion wiki status --vault-root ~/my-vault"
Enter
Sleep 500ms
Type '{"raw_files": 1, "ingested": 1, "articles": 8, "entities": 3, "topics": 5}'
Enter
Sleep 1.5s

Type "# One file in. 8 wiki articles out. Compile, don't retrieve."
Enter
Sleep 2s
