#!/usr/bin/env bash
# spawn.sh — run one fresh-context task agent headless, from a brief file.
# Optional: for a harness without a subagent tool, for a task that should run
# on another vendor's model, or to drive a build from a plain shell.
#
#   spawn.sh --brief=FILE --class=low|mid|strong [--cwd=DIR] [--timeout=SECONDS] [--log=FILE]
#
# The command for each class comes from the environment:
#   NEW_PROJECT_RUNNER_LOW, NEW_PROJECT_RUNNER_MID, NEW_PROJECT_RUNNER_STRONG
# Each is a shell command line that starts a headless agent CLI. If it contains
# {brief}, that is replaced by the brief's absolute path; otherwise the brief is
# piped to the command's stdin. Record your own in reference/defaults.md
# § Custom instructions, for example:
#   export NEW_PROJECT_RUNNER_LOW='claude -p --model <haiku model id>'
#   export NEW_PROJECT_RUNNER_MID='gemini -m <flash model id> -p "$(cat {brief})"'
#
# The agent's output streams to stdout and to the log (default:
# .orchestrator/logs/<brief name>.log next to the briefs directory). The exit
# status is the CLI's; 124 means the timeout fired (default two hours). The
# agent gets the brief and nothing else: never run this from inside another
# agent's session with extra instructions.
set -euo pipefail

BRIEF=""; CLASS=""; CWD="."; TIMEOUT="7200"; LOG=""
for arg in "$@"; do
  case "$arg" in
    --brief=*) BRIEF="${arg#--brief=}" ;;
    --class=*) CLASS="${arg#--class=}" ;;
    --cwd=*) CWD="${arg#--cwd=}" ;;
    --timeout=*) TIMEOUT="${arg#--timeout=}" ;;
    --log=*) LOG="${arg#--log=}" ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done
die() { echo "spawn.sh: $*" >&2; exit 2; }

[ -n "$BRIEF" ] && [ -f "$BRIEF" ] || die "--brief=FILE is required and must exist"
case "$CLASS" in low|mid|strong) ;; *) die "--class must be low, mid or strong" ;; esac
[ -d "$CWD" ] || die "no such directory: $CWD"
BRIEF="$(cd "$(dirname "$BRIEF")" && pwd -P)/$(basename "$BRIEF")"
if grep -q '__[A-Z_]*__\|<[a-z][a-z /-]*>' "$BRIEF"; then
  echo "spawn.sh: warning: the brief still contains placeholders:" >&2
  grep -n '__[A-Z_]*__\|<[a-z][a-z /-]*>' "$BRIEF" | head -5 | sed 's/^/  /' >&2
fi

VAR="NEW_PROJECT_RUNNER_$(printf '%s' "$CLASS" | tr '[:lower:]' '[:upper:]')"
CMD="${!VAR:-}"
[ -n "$CMD" ] || die "$VAR is not set. Export it as the headless CLI command for the '$CLASS' class (see the header of this script)."

[ -n "$LOG" ] || LOG="$(dirname "$BRIEF")/../logs/$(basename "${BRIEF%.md}").log"
mkdir -p "$(dirname "$LOG")"

STDIN=/dev/null
if [[ "$CMD" == *"{brief}"* ]]; then
  CMD="${CMD//\{brief\}/$BRIEF}"
else
  STDIN="$BRIEF"
fi
TO=()
if command -v timeout >/dev/null 2>&1; then TO=(timeout "$TIMEOUT"); fi

cd "$CWD"
{
  echo "[spawn] $(date -Is) class=$CLASS cwd=$(pwd -P)"
  echo "[spawn] brief=$BRIEF"
  echo "[spawn] cmd=$CMD"
} | tee -a "$LOG"
set +e
${TO[@]+"${TO[@]}"} bash -c "$CMD" < "$STDIN" 2>&1 | tee -a "$LOG"
STATUS=${PIPESTATUS[0]}
set -e
echo "[spawn] $(date -Is) exit $STATUS" | tee -a "$LOG"
exit "$STATUS"
