#!/usr/bin/env bash
# law.sh — seal, verify and unlock the law files of a project built with the
# new-project skill. Run it from the project root.
#
#   law.sh seal            Checksum every law file and make it read-only.
#                          Refuses if a file that was already sealed has changed.
#   law.sh seal --amend    Re-seal after an amendment the user authorized.
#   law.sh verify          Check that no sealed file has changed or gone missing.
#   law.sh unlock FILE...  Make sealed files writable for an authorized amendment.
#
# Law files are everything under agents/ (except the manifest itself) plus
# docs/ARCHITECTURE.md. A file whose "Status:" line, within its first five
# lines, reads "IN PROGRESS" is a working file (the build ledger) and is left
# unsealed until that status changes. The build's live state (.orchestrator/)
# lives outside agents/ on purpose: it is not law and is never sealed.
#
# Read-only permissions are a speed bump, not a lock: the checksums are what
# prove nothing changed. Run `sha256sum -c agents/MANIFEST.sha256` in CI too.
set -euo pipefail

MANIFEST="agents/MANIFEST.sha256"

if command -v sha256sum >/dev/null 2>&1; then
  SHA="sha256sum"
else
  SHA="shasum -a 256"
fi

die() { echo "law.sh: $*" >&2; exit 1; }

in_progress() { head -n 5 "$1" | grep -q '^Status: IN PROGRESS'; }

# Every file that should be sealed right now, one per line, sorted.
law_files() {
  {
    find agents -type f ! -path "$MANIFEST" ! -path "$MANIFEST.tmp"
    if [ -f docs/ARCHITECTURE.md ]; then echo docs/ARCHITECTURE.md; fi
  } | LC_ALL=C sort | while IFS= read -r f; do
    in_progress "$f" || printf '%s\n' "$f"
  done
}

# Every file under agents/ that is a working file, one per line, sorted.
working_files() {
  find agents -type f ! -path "$MANIFEST" ! -path "$MANIFEST.tmp" | LC_ALL=C sort |
    while IFS= read -r f; do
      if in_progress "$f"; then printf '%s\n' "$f"; fi
    done
}

sealed_files() {
  sed -E 's/^[0-9a-f]+ [ *]//' "$MANIFEST" | LC_ALL=C sort
}

indent() { sed 's/^/  /'; }

# Prints every sealed file that changed or is missing; returns non-zero if any.
check() {
  local out status=0
  out=$($SHA -c "$MANIFEST" 2>&1) || status=$?
  if [ "$status" -ne 0 ]; then
    printf '%s\n' "$out" | grep -v ': OK$' >&2 || true
  fi
  return "$status"
}

cmd_verify() {
  [ -f "$MANIFEST" ] || die "nothing is sealed yet ($MANIFEST not found)"
  check || die "sealed law files have changed. Stop and tell the user."
  echo "OK: $(wc -l < "$MANIFEST" | tr -d ' ') sealed file(s) unchanged."
  local new working
  new=$(LC_ALL=C comm -23 <(law_files) <(sealed_files))
  working=$(working_files)
  if [ -n "$new" ]; then echo "New since the last seal (not yet sealed):"; printf '%s\n' "$new" | indent; fi
  if [ -n "$working" ]; then echo "Working files (IN PROGRESS, not sealed):"; printf '%s\n' "$working" | indent; fi
}

cmd_seal() {
  local mode="${1:-}" dropped=""
  [ -z "$mode" ] || [ "$mode" = "--amend" ] || die "unknown option: $mode"
  [ -n "$(law_files)" ] || die "no law files found under agents/"
  if [ -f "$MANIFEST" ]; then
    if [ "$mode" != "--amend" ]; then
      check || die "a sealed file has changed. Changing law needs the user's authorization; after an authorized amendment use: law.sh seal --amend"
    fi
    dropped=$(LC_ALL=C comm -13 <(law_files) <(sealed_files))
    chmod u+w "$MANIFEST"
  fi
  law_files | tr '\n' '\0' | xargs -0 $SHA > "$MANIFEST.tmp"
  mv -f "$MANIFEST.tmp" "$MANIFEST"
  law_files | tr '\n' '\0' | xargs -0 chmod a-w
  chmod a-w "$MANIFEST"
  echo "Sealed $(wc -l < "$MANIFEST" | tr -d ' ') file(s) in $MANIFEST."
  if [ -n "$dropped" ]; then
    echo "Warning: previously sealed, no longer sealed (deleted or marked IN PROGRESS):" >&2
    printf '%s\n' "$dropped" | indent >&2
  fi
}

cmd_unlock() {
  [ "$#" -gt 0 ] || die "name the files to unlock"
  local f
  for f in "$@"; do
    [ -f "$f" ] || die "no such file: $f"
    chmod u+w "$f"
  done
  echo "Unlocked $# file(s). Make only the authorized change, log it in agents/AMENDMENTS.md, then run: law.sh seal --amend"
}

[ -d agents ] || die "no agents/ directory here. Run from the project root."

case "${1:-}" in
  seal)   shift; cmd_seal "$@" ;;
  verify) cmd_verify ;;
  unlock) shift; cmd_unlock "$@" ;;
  *)      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
