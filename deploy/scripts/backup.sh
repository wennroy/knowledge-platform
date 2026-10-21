#!/usr/bin/env bash
# Knowledge Platform backup script.
#
# Usage:
#   bash deploy/scripts/backup.sh [dest-dir]
#
# Default dest-dir is ./backups (relative to where the script is run).
# What gets backed up:
#   1. vault/  -> <dest-dir>/vault-<timestamp>.bundle (git bundle, --all refs)
#   2. lancedb data dir at /data/lancedb (skipped if the path doesn't exist)
#      -> <dest-dir>/lancedb-<timestamp>.tgz

set -euo pipefail

DEST="${1:-./backups}"
TS="$(date +%Y%m%d-%H%M%S)"

VAULT_REPO="/Users/wennroy/proj/knowledge-platform/vault"
LANCEDB_DIR="/data/lancedb"

mkdir -p "$DEST"

paths=()

# 1. vault as a portable git bundle
# `git -C <dir> rev-parse --git-dir` is the canonical "is this a working repo?" probe.
# Some installs pre-create an empty $VAULT/.git/ as a placeholder; we skip those.
if git -C "$VAULT_REPO" rev-parse --git-dir >/dev/null 2>&1; then
    bundle="$DEST/vault-$TS.bundle"
    git -C "$VAULT_REPO" bundle create "$bundle" --all
    paths+=("$bundle")
else
    echo "WARN: $VAULT_REPO is not a valid git repo; skipping vault bundle" >&2
fi

# 2. lancedb raw data (only when the source path actually exists)
if [[ -d "$LANCEDB_DIR" ]]; then
    archive="$DEST/lancedb-$TS.tgz"
    tar czf "$archive" -C /data lancedb
    paths+=("$archive")
else
    echo "WARN: $LANCEDB_DIR not found; skipping lancedb archive" >&2
fi

if (( ${#paths[@]} == 0 )); then
    echo "Backup complete: (nothing backed up)" >&2
    exit 1
fi

echo "Backup complete: ${paths[*]}"
