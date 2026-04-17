# Obsidian Legion — Terminal Intro Animation
# Clean version: no ASCII art (bash can't handle it), pure Nostromo text
# Run: vhs tui-intro.tape

Output tui-intro.gif

Set Shell "bash"
Set FontSize 16
Set Width 800
Set Height 450
Set Theme "Catppuccin Mocha"
Set Padding 30
Set TypingSpeed 30ms

# --- Cold boot ---
Sleep 1s
Type "echo ''"
Enter
Type "echo '  OBSIDIAN LEGION v0.2.0'"
Enter
Type "echo '  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Type "echo '  One contract. Every agent. Zero sludge.'"
Enter
Type "echo ''"
Enter
Sleep 1.5s

# --- 3-Layer Architecture ---
Type "echo '  >>> 3-Layer Memory Architecture'"
Enter
Sleep 500ms

Type "echo '  Layer 1: Obsidian CLI + Legion ........... [ONLINE]'"
Enter
Sleep 400ms

Type "echo '  Layer 2: LLM Wiki (Karpathy pattern) .... [ONLINE]'"
Enter
Sleep 400ms

Type "echo '  Layer 3: Qdrant Vector Search ............ [ONLINE]'"
Enter
Sleep 400ms

Type "echo ''"
Enter

# --- Status ---
Sleep 500ms
Type "echo '  >>> All systems operational.'"
Enter
Type "echo '  >>> Ready for consciousness.'"
Enter
Sleep 2.5s
