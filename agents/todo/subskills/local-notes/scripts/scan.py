#!/usr/bin/env python3
"""List candidate action items in text files changed inside a time window.

Used by the local-notes subskill. It does the deterministic part (which files, which
lines) so the agent only has to judge the few lines that come back. Read-only.

    scan.py --dir DIR --glob GLOB --since ISO --until ISO [--owner NAME]...
            [--home PATH] [--max-candidates N] [--include-checked]

DIR is taken relative to --home (or $TODO_HOME, or the current directory) unless it is
absolute. A naive --since/--until is read as local time. Prints one JSON object to
stdout. Exit codes: 0 scanned, 2 bad arguments or the directory is unusable.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

MAX_FILE_BYTES = 1_000_000
MAX_LINE_CHARS = 300

RE_UNCHECKED = re.compile(r"^\s*[-*+]\s+\[ \]\s")
RE_CHECKED = re.compile(r"^\s*[-*+]\s+\[[xX]\]\s")
RE_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
RE_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
RE_ACTION_HEADING = re.compile(r"action|to-?do|next steps?|follow-?ups?", re.I)
RE_KEYWORDS = [
    ("todo", re.compile(r"\bTODO\b")),
    ("action", re.compile(r"\bACTION\b")),
    ("ai", re.compile(r"\bAI:")),
    ("action-item", re.compile(r"\baction items?\b", re.I)),
]
RE_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


def fail(message: str, code: int = 2) -> int:
    print(json.dumps({"error": message, "candidates": []}, indent=2))
    return code


def parse_when(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.astimezone()


def clip(text: str) -> str:
    text = text.rstrip()
    return text if len(text) <= MAX_LINE_CHARS else text[:MAX_LINE_CHARS - 1] + "…"


def file_date(name: str, lines: list[str], mtime: datetime) -> tuple[str, str]:
    """A date for the file's ref: from its name, else its first lines, else mtime."""
    m = RE_DATE.search(name)
    if m:
        return m.group(1), "name"
    for line in lines[:10]:
        m = RE_DATE.search(line)
        if m:
            return m.group(1), "content"
    return mtime.date().isoformat(), "mtime"


def neighbour(lines: list[str], index: int, step: int) -> str:
    i = index + step
    while 0 <= i < len(lines):
        if lines[i].strip():
            return clip(lines[i].strip())
        i += step
    return ""


def scan_file(path: Path, rel: str, mtime: datetime, owners: list[re.Pattern],
              include_checked: bool = False) -> tuple[dict, list]:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    fdate, source = file_date(path.name, lines, mtime)
    info = {"file": rel, "modified": mtime.isoformat(timespec="seconds"),
            "file_date": fdate, "date_source": source}
    found = []
    under_action_heading = False
    for i, line in enumerate(lines):
        h = RE_HEADING.match(line)
        if h:
            under_action_heading = bool(RE_ACTION_HEADING.search(h.group(1)))
            continue
        if not line.strip():
            continue
        kinds = []
        if RE_CHECKED.match(line):
            if not include_checked:
                continue
            kinds.append("checked")
        if RE_UNCHECKED.match(line):
            kinds.append("checkbox")
        for kind, rx in RE_KEYWORDS:
            if rx.search(line):
                kinds.append(kind)
        if any(rx.search(line) for rx in owners):
            kinds.append("owner")
        if under_action_heading and RE_BULLET.match(line) and not kinds:
            kinds.append("under-action-heading")
        if kinds:
            found.append({"file": rel, "line": i + 1, "modified": info["modified"],
                          "file_date": fdate, "kinds": kinds, "text": clip(line.strip()),
                          "before": neighbour(lines, i, -1), "after": neighbour(lines, i, 1)})
    return info, found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--glob", default="**/*.md")
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--owner", action="append", default=[], help="a name that means the user")
    ap.add_argument("--home", default=None)
    ap.add_argument("--max-candidates", type=int, default=200)
    ap.add_argument("--include-checked", action="store_true",
                    help="also return ticked checkboxes (evidence that something is done)")
    args = ap.parse_args(argv)

    try:
        since, until = parse_when(args.since), parse_when(args.until)
    except ValueError as exc:
        return fail(f"--since/--until must be ISO 8601 date-times: {exc}")

    base = Path(os.path.expanduser(args.dir))
    if not base.is_absolute():
        home = args.home or os.environ.get("TODO_HOME") or os.getcwd()
        base = Path(os.path.expanduser(home)) / base
    base = Path(os.path.abspath(base))
    if not base.is_dir():
        return fail(f"directory not found: {base}")
    pattern = args.glob
    if os.path.isabs(pattern) or ".." in Path(pattern).parts:
        return fail(f"--glob {pattern!r} must be relative and must not contain '..'")

    owners = [re.compile(rf"(?<![\w@])@{re.escape(o)}(?!\w)", re.I) for o in args.owner if o]
    base_real = base.resolve()
    files, skipped, candidates = [], [], []
    matched = 0
    for path in sorted(base.glob(pattern)):
        try:
            if not path.is_file():
                continue
            matched += 1
            real = path.resolve()
            if not real.is_relative_to(base_real):
                skipped.append({"file": str(path), "reason": "outside the directory"})
                continue
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).astimezone()
            if not (since <= mtime <= until):
                continue
            rel = path.relative_to(base).as_posix()
            if stat.st_size > MAX_FILE_BYTES:
                skipped.append({"file": rel, "reason": f"larger than {MAX_FILE_BYTES} bytes"})
                continue
            info, found = scan_file(path, rel, mtime, owners, args.include_checked)
            files.append(info)
            candidates += found
        except OSError as exc:
            skipped.append({"file": str(path), "reason": str(exc)})
    candidates.sort(key=lambda c: (c["modified"], c["file"], c["line"]), reverse=False)
    candidates.sort(key=lambda c: c["modified"], reverse=True)
    truncated = len(candidates) > args.max_candidates
    print(json.dumps({
        "dir": str(base), "glob": pattern,
        "window": {"since": since.isoformat(timespec="seconds"),
                   "until": until.isoformat(timespec="seconds")},
        "files_matched": matched, "files_in_window": len(files), "files": files,
        "candidates": candidates[:args.max_candidates], "truncated": truncated,
        "skipped": skipped,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
