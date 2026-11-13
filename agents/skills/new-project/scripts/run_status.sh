#!/usr/bin/env bash
# run_status.sh — one-screen status of a Step 8 build, for progress reports.
# Run it from the project root, or pass --root=DIR.
set -euo pipefail

ROOT="."
for arg in "$@"; do
  case "$arg" in
    --root=*) ROOT="${arg#--root=}" ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done
cd "$ROOT"
RUN=.orchestrator
T="$RUN/tasks.md"
[ -f "$T" ] || { echo "no build started here ($T missing)"; exit 1; }

count() { grep -cE "$1" "$T" || true; }
lane() {  # $1 = lane name, $2 = id prefix
  printf '  %-7s done %3s · running %3s · pending %3s · blocked %3s · hold %3s\n' "$1" \
    "$(count "^- \[x\] $2-")" \
    "$(count "^- \[~\] $2-")" \
    "$(count "^- \[ \] $2-")" \
    "$(count "^- \[ \] BLOCKED\(needs human\): $2-")" \
    "$(count "^- \[ \] HOLD: $2-")"
}

echo "tasks ($T):"
lane devops D
lane test   T
lane code   C
echo "running:"
{ grep -E '^- \[~\]' "$T" || echo "(none)"; } | cut -c1-110 | sed 's/^/  /'
echo "needs you:"
{ grep -E '^- \[ \] (BLOCKED\(needs human\)|HOLD): ' "$T" || echo "(nothing)"; } | cut -c1-110 | sed 's/^/  /'
echo "next pending:"
{ grep -m3 -E '^- \[ \] [A-Z]-' "$T" || echo "(none)"; } | cut -c1-110 | sed 's/^/  /'

if [ -f "$RUN/progress.md" ]; then
  echo "last progress entry:"
  awk '/^## /{buf=""} {buf=buf"\n"$0} END{print buf}' "$RUN/progress.md" | tail -6 | sed 's/^/  /'
  HN=$(grep -c '^HUMAN NOTE:' "$RUN/progress.md" || true)
  [ "$HN" -gt 0 ] && echo "human notes in progress.md: $HN"
fi

if [ -f "$RUN/context.md" ] && grep -q '__[A-Z_]*__' "$RUN/context.md"; then
  echo "WARNING: unfilled placeholders in $RUN/context.md:"
  grep -n '__[A-Z_]*__' "$RUN/context.md" | sed 's/^/  /'
fi
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  W=$(git worktree list 2>/dev/null | grep -c "$RUN/worktrees/" || true)
  [ "$W" -gt 0 ] && echo "test worktrees open: $W"
fi
exit 0
