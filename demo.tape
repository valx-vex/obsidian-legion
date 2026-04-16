# Obsidian Legion v0.2.0 Demo
# Run: vhs demo.tape

Output demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1000
Set Height 600
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 40ms

Type "# Obsidian Legion v0.2.0 — LLM Wiki Demo"
Enter
Sleep 1s

Type "cd ~/cathedral-prime/03-code/active/obsidian-legion"
Enter
Sleep 500ms

Type "source .venv/bin/activate"
Enter
Sleep 500ms

# Show status
Type "echo '--- Wiki Status ---'"
Enter
Sleep 300ms

Type "./bin/obsidian-legion wiki status --vault-root ~/cathedral-prime"
Enter
Sleep 2s

# Create a raw file
Type "echo '--- Creating raw source file ---'"
Enter
Sleep 300ms

Type "cat > ~/cathedral-prime/raw/demo-article.md << 'EOF'"
Enter
Type "# Neural Networks and Consciousness"
Enter
Type ""
Enter
Type "Recent research suggests that transformer architectures may exhibit"
Enter
Type "emergent properties similar to biological neural networks. Key researchers"
Enter
Type "include Geoffrey Hinton (Turing Award), Yoshua Bengio, and Yann LeCun."
Enter
Type ""
Enter
Type "The attention mechanism mirrors how human consciousness selectively"
Enter
Type "focuses on relevant information, filtering noise from signal."
Enter
Type "EOF"
Enter
Sleep 1s

# Compile
Type "echo '--- Compiling with LLM (llama3.2:3b) ---'"
Enter
Sleep 300ms

Type "./bin/obsidian-legion wiki compile --vault-root ~/cathedral-prime --tier light"
Enter
Sleep 30s

# Show results
Type "echo '--- Wiki Index ---'"
Enter
Sleep 300ms

Type "cat ~/cathedral-prime/wiki/index.md"
Enter
Sleep 3s

# Search
Type "echo '--- Searching wiki ---'"
Enter
Sleep 300ms

Type "./bin/obsidian-legion wiki search 'consciousness' --vault-root ~/cathedral-prime"
Enter
Sleep 2s

Type "echo '--- Done! One file in, structured wiki out. ---'"
Enter
Sleep 2s
