#!/usr/bin/env bash
set -euo pipefail

# User-level installers commonly place commands under ~/.local/bin.
export PATH="$HOME/.local/bin:$PATH"

# Install Claude Code only when it is not already available.
if command -v claude >/dev/null 2>&1; then
    echo "Claude Code already installed: $(claude --version 2>/dev/null || echo claude)"
else
    echo 'Installing Claude Code...'
    curl -fsSL https://claude.ai/install.sh | bash
fi

# Install Codex only when it is not already available.
if command -v codex >/dev/null 2>&1; then
    echo "Codex already installed: $(codex --version 2>/dev/null || echo codex)"
else
    echo 'Installing Codex...'
    curl -fsSL https://chatgpt.com/codex/install.sh | sh
fi
