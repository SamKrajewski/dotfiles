#!/usr/bin/env bash
# run_init.sh — start the Step 8 run directory for a project built with the
# new-project skill. Run it from the project root.
#
#   run_init.sh [--from=agents/prd.md] [--force]
#
# Creates the git-ignored .orchestrator/ directory:
#   tasks.md     the task list copied from the "Tasks" section of --from (the
#                live checklist; only the status markers change there)
#   context.md   the shared context for code and devops agents, copied from
#                reference/context.md.tmpl with __PLACEHOLDERS__ to fill in
#   progress.md  the append-only learnings log
#   briefs/ logs/ worktrees/
# and makes sure .orchestrator/ is ignored, so it can never reach a commit or a
# test agent's worktree.
#
# --force replaces tasks.md from --from (the old one is kept as
# tasks.<timestamp>.md) and keeps an existing context.md and progress.md.
# Use it to start a feature build: --from=agents/features/<n>-<slug>.md --force
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FROM="agents/prd.md"; FORCE=""
for arg in "$@"; do
  case "$arg" in
    --from=*) FROM="${arg#--from=}" ;;
    --force) FORCE=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done
die() { echo "run_init.sh: $*" >&2; exit 1; }

RUN=.orchestrator
[ -d agents ] || die "no agents/ directory here. Run from the project root."
[ -f "$FROM" ] || die "no such file: $FROM (freeze the PRD first)"
if [ -e "$RUN/tasks.md" ] && [ -z "$FORCE" ]; then
  die "$RUN/tasks.md exists: a build is already started. Resume it (orchestrator.md § Resuming), or pass --force to replace the task list."
fi
mkdir -p "$RUN/briefs" "$RUN/logs" "$RUN/worktrees"

# 1. Keep the run directory out of git.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if ! git check-ignore -q "$RUN"; then
    printf '\n# new-project build state: never committed, never visible to test agents\n/.orchestrator/\n' >> .gitignore
    echo "[init] added /.orchestrator/ to .gitignore"
    if git rev-parse --verify -q HEAD >/dev/null; then
      # Commit just this file, so the first task's scope check starts from a clean tree.
      git add -- .gitignore
      git commit -q -m "Ignore .orchestrator/ build state" -- .gitignore && echo "[init] committed .gitignore"
    else
      echo "[init] no commits yet: the scaffold task commits .gitignore with the law files" >&2
    fi
  fi
  git check-ignore -q "$RUN" || die "$RUN is still not ignored; fix .gitignore before continuing"
  if [ -n "$(git ls-files "$RUN")" ]; then
    die "files under $RUN are tracked. Run: git rm -r --cached $RUN"
  fi
else
  echo "[init] warning: not a git repository yet. The scaffold task creates it; $RUN must stay ignored." >&2
fi

# 2. tasks.md: the Tasks section, verbatim.
TMP="$RUN/tasks.md.tmp"
awk '/^## /{in_tasks = ($0 ~ /Tasks/)} in_tasks{print}' "$FROM" > "$TMP"
grep -q '^- \[ \]' "$TMP" || { rm -f "$TMP"; die "no '- [ ]' task lines found in the Tasks section of $FROM"; }
if [ -e "$RUN/tasks.md" ]; then
  OLD="$RUN/tasks.$(date +%Y%m%d-%H%M%S).md"
  mv "$RUN/tasks.md" "$OLD"
  echo "[init] previous checklist kept as $OLD"
fi
{
  printf '# Tasks — live checklist (copied from %s on %s)\n' "$FROM" "$(date -Is)"
  printf '# Markers: [ ] pending · [~] running · [x] done · "BLOCKED(needs human): " · "HOLD: " (user).\n'
  printf '# The definitions are law; only the markers change here. New or changed tasks go through amend.md.\n\n'
  cat "$TMP"
} > "$RUN/tasks.md"
rm -f "$TMP"

# 3. context.md and progress.md (kept if they already exist).
PROJECT="$(grep -m1 '^# ' "$FROM" | sed -E 's/^# *//; s/^(PRD|Feature [0-9]+) *[—-] *//')"
PROJECT_ESC="$(printf '%s' "$PROJECT" | sed 's/[&|\\]/\\&/g')"
if [ ! -e "$RUN/context.md" ]; then
  sed -e "s|__PROJECT__|$PROJECT_ESC|g" "$SKILL_DIR/reference/context.md.tmpl" > "$RUN/context.md"
  echo "[init] wrote $RUN/context.md from the template"
fi
if [ ! -e "$RUN/progress.md" ]; then
  printf '# Progress log — %s\nStarted: %s\nLines starting with "HUMAN NOTE:" are steering from the user and override anything else here.\n---\n' \
    "$PROJECT" "$(date -Is)" > "$RUN/progress.md"
else
  printf '## %s · ORCHESTRATOR · new task list from %s\n---\n' "$(date -Is)" "$FROM" >> "$RUN/progress.md"
fi

N=$(grep -c '^- \[ \]' "$RUN/tasks.md" || true)
cat <<EOF

[init] $RUN ready: $N task(s) in tasks.md (from $FROM)
  context.md  -> fill every __PLACEHOLDER__ from the law files (run_status.sh warns while any remains)
  progress.md -> leave as is, or add 'HUMAN NOTE:' lines
  next        -> open the ledger (Status: IN PROGRESS), then run the scaffold task through the loop
EOF
