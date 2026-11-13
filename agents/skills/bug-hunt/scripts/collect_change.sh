#!/usr/bin/env bash
# Collects a change (git, jj, or a plain diff file) into .review/tmp/change.json.
# Thin wrapper so the skill can be invoked from any shell; the logic is in
# collect_change.py (python3, standard library only).
#
# Usage: collect_change.sh [BASE] [HEAD] [--vcs auto|git|jj|diff] [--diff-file F]
#                          [--review-dir DIR] [--out FILE] [--no-pr] [--no-init]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py="$(command -v python3 || command -v python || true)"
if [[ -z "$py" ]]; then
  echo "collect_change.sh: python3 is required" >&2
  exit 1
fi
exec "$py" "$here/collect_change.py" "$@"
