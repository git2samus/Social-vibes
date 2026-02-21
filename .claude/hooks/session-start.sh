#!/bin/bash
# SessionStart hook for Social-vibes
# Installs gh CLI and configures GH_REPO so `gh pr create` works in
# the Default Cloud Environment without any extra flags.
set -euo pipefail

# Only run in remote (web) sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Install gh CLI if not already present (available in Ubuntu 24.04 apt)
if ! command -v gh &>/dev/null; then
  echo "[session-start] Installing gh CLI..."
  apt-get install -y gh 2>&1 | tail -3
  echo "[session-start] gh $(gh --version | head -1) installed."
fi

# Derive GH_REPO (owner/repo) from the git proxy URL so gh commands
# don't need --repo flags.  Proxy URL format:
#   http://local_proxy@127.0.0.1:PORT/git/OWNER/REPO
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  REMOTE_URL=$(git -C "${CLAUDE_PROJECT_DIR:-.}" remote get-url origin 2>/dev/null || true)
  if [ -n "$REMOTE_URL" ]; then
    GH_REPO_VALUE=$(echo "$REMOTE_URL" | sed 's|.*/git/||')
    echo "export GH_REPO=$GH_REPO_VALUE" >> "$CLAUDE_ENV_FILE"
    echo "[session-start] GH_REPO set to $GH_REPO_VALUE"
  fi
fi
