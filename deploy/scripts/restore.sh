#!/usr/bin/env bash
# Knowledge Platform restore script.
#
# Usage:
#   bash deploy/scripts/restore.sh <vault-bundle>
#
# Restores the vault/ directory from a git bundle created by backup.sh.
#
# The bundled data is intentionally limited to the vault (notes source-of-truth).
# LanceDB is NOT restored from a tgz here — on next start the backend performs
# its startup reconcile against the just-restored vault and rebuilds the
# vector index from scratch. This is simpler, version-safe, and avoids
# restoring a stale on-disk index that disagrees with the file content.
#
# WARNING: if /Users/wennroy/proj/knowledge-platform/vault/ already contains
# files, `git clone` would refuse to write into a non-empty directory. We warn
# and bail out instead of overwriting silently — remove or move the existing
# vault first if you really want to overwrite.

set -euo pipefail

BUNDLE="${1:-}"
VAULT_DIR="/Users/wennroy/proj/knowledge-platform/vault"

if [[ -z "$BUNDLE" ]]; then
    echo "Usage: $0 <vault-bundle>" >&2
    exit 2
fi
if [[ ! -f "$BUNDLE" ]]; then
    echo "Bundle not found: $BUNDLE" >&2
    exit 1
fi

# Refuse to clobber an existing (non-empty) vault.
if [[ -d "$VAULT_DIR" ]] && [[ -n "$(ls -A "$VAULT_DIR" 2>/dev/null || true)" ]]; then
    echo "Refusing to restore: $VAULT_DIR is not empty." >&2
    echo "Move or delete its contents first if you really want to overwrite." >&2
    exit 3
fi

mkdir -p "$(dirname "$VAULT_DIR")"
# `git clone <bundle> <dir>` initialises a fresh repo at <dir>.
git clone "$BUNDLE" "$VAULT_DIR"

cat <<EOF
Restore complete: vault materialised at $VAULT_DIR
Next: start the backend (docker compose up -d). Its startup reconcile will
rebuild the LanceDB index from the restored vault — no manual lancedb restore
is needed.
EOF
