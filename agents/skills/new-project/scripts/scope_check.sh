#!/usr/bin/env bash
# scope_check.sh — did a task agent touch only the files its brief allowed?
#
#   scope_check.sh [--cwd=DIR] [--base=REF] -- <allowed path or pattern>...
#
# Lists every file changed in the work tree (staged, unstaged and untracked)
# against HEAD (or --base), and fails if any is not covered by an allowed
# pattern. Patterns use bash matching, where * also crosses slashes:
#   src/util/duration.py   tests/util/*   .github/workflows/ci.yml
# A directory name allows everything under it. Files under agents/ are never
# allowed unless named exactly: law is not edited by task agents.
#
# Exit 0 = in scope. 1 = out of scope (offending files listed; revert them and
# count the attempt as failed). 2 = usage error.
set -euo pipefail

CWD="."; BASE="HEAD"
while [ $# -gt 0 ]; do
  case "$1" in
    --cwd=*) CWD="${1#--cwd=}"; shift ;;
    --base=*) BASE="${1#--base=}"; shift ;;
    --) shift; break ;;
    -*) echo "unknown arg: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: scope_check.sh [--cwd=DIR] [--base=REF] -- <allowed>..." >&2; exit 2; }
cd "$CWD"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "scope_check.sh: not a git work tree: $CWD" >&2; exit 2; }

changed=$( { git diff --name-only "$BASE" -- ; git ls-files --others --exclude-standard; } | LC_ALL=C sort -u )
bad=0; n=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  n=$((n + 1))
  ok=0
  for pat in "$@"; do
    pat="${pat%/}"
    # shellcheck disable=SC2053
    if [[ "$f" == $pat || "$f" == $pat/* ]]; then ok=1; break; fi
  done
  if [ "$ok" -eq 1 ] && [[ "$f" == agents/* ]]; then
    ok=0
    for pat in "$@"; do [ "$pat" = "$f" ] && ok=1; done
  fi
  if [ "$ok" -eq 0 ]; then echo "OUT OF SCOPE: $f"; bad=1; fi
done <<< "$changed"

if [ "$bad" -eq 0 ]; then
  echo "scope ok: $n changed file(s), all within the brief"
  exit 0
fi
echo "scope_check.sh: the agent changed files outside its brief. Revert them (git checkout -- <file>; git clean -f <file>) and count the attempt as failed." >&2
exit 1
