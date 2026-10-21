#!/usr/bin/env bash
# Install the knowledge-platform git hooks into the vault repository.
#
# Usage:
#   bash deploy/scripts/install-git-hooks.sh [vault-path]
#
# Default vault path: ./vault (relative to the repo root).
#
# The vault may be a separate git repository (recommended for teams) or the
# in-repo ./vault directory. In both cases the hook is installed into
# <vault>/.git/hooks/post-commit.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VAULT_PATH="${1:-${REPO_ROOT}/vault}"
HOOK_SRC="${REPO_ROOT}/deploy/hooks/post-commit"
HOOK_DST="${VAULT_PATH}/.git/hooks/post-commit"

if [[ ! -f "${HOOK_SRC}" ]]; then
    echo "ERROR: hook source not found: ${HOOK_SRC}" >&2
    exit 1
fi

if [[ ! -d "${VAULT_PATH}/.git" ]]; then
    echo "Initializing git repository in ${VAULT_PATH}..."
    git -C "${VAULT_PATH}" init -q
fi

mkdir -p "$(dirname "${HOOK_DST}")"
cp "${HOOK_SRC}" "${HOOK_DST}"
chmod +x "${HOOK_DST}"

echo "Installed post-commit hook -> ${HOOK_DST}"
echo
echo "Set KB_BACKEND_URL if your backend is not at http://backend:8000, e.g.:"
echo "  export KB_BACKEND_URL=http://localhost:8000"
