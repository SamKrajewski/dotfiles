#!/usr/bin/env python3
"""Bookkeeping CLI for the daily TODO skill.

It does what should not depend on a model's judgment: dates and time windows, the run
lock, backups, id counters, trimming and archiving, and validation of the workspace
files against references/state-format.md. Python standard library only (3.11+).

JSON results go to stdout, diagnostics to stderr.
Exit codes: 0 success, 1 validation errors (lint, finish), 2 usage/config/workspace
problem, 3 another run holds the lock.

Environment: TODO_HOME (workspace), TODO_NOW (ISO 8601 clock override; a naive value
is read in the configured time zone), XDG_CONFIG_HOME (location of the pointer file).
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:  # zoneinfo needs tz data on the machine; "local" works without it
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

SKILL_DIR = Path(__file__).resolve().parent.parent

EXIT_OK, EXIT_INVALID, EXIT_USAGE, EXIT_LOCKED = 0, 1, 2, 3

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SECTIONS = ["Goals", "Other tasks", "Proposed", "Parked", "Dismissed"]
TASK_SECTIONS = ("Goals", "Other tasks", "Proposed", "Parked")
OPEN_SECTIONS = ("Goals", "Other tasks")
VERBS = ["done", "progress", "added", "changed", "dropped", "corrected", "prepared",
         "sources", "note"]
TASK_KEYS = {"src", "due", "next", "waiting", "nudge", "draft", "note", "proposed",
             "parked"}
GOAL_KEYS = {"due", "parked", "note", "src"}
DATE_KEYS = {"due", "nudge", "proposed", "parked"}
SOURCE_STATUSES = ("ok", "partial", "unavailable", "failed")
BRIEF_REQUIRED = ["Focus today", "Since last run", "Needs your input", "Prepared for you",
                  "Sources"]
BRIEF_OPTIONAL = ["Schedule", "Follow-ups due", "FYI"]
RESERVED_SUBSKILLS = ("create-subskill",)
STATE_SCHEMA = 1

TASK_FORMAT = "- [ ] T<n> | P<0-3> | <title> | src: <where it came from>"


class TodoError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE):
        super().__init__(message)
        self.message = message
        self.code = code


# --------------------------------------------------------------------------- utilities

def split_lines(text: str) -> list[str]:
    """Split on \\n, \\r\\n and \\r only, so line numbers match what an editor shows."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def read_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def emit(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def note(msg: str) -> None:
    print(f"todo.py: {msg}", file=sys.stderr)


def num(task_id: str) -> int:
    m = re.search(r"(\d+)", task_id)
    return int(m.group(1)) if m else 0


# ----------------------------------------------------------------------------- clock

class Zone:
    """The configured time zone: 'local' or an IANA name."""

    def __init__(self, name: str):
        self.name = name
        self.tz = None
        if name != "local":
            if ZoneInfo is None:
                raise TodoError("run.timezone: zoneinfo is not available here; use \"local\"")
            try:
                self.tz = ZoneInfo(name)
            except Exception:
                raise TodoError(f"run.timezone: unknown time zone {name!r}; use \"local\" or an "
                                f"IANA name such as \"America/New_York\"")

    def localize(self, naive: datetime) -> datetime:
        if self.tz is None:
            return naive.astimezone()
        return naive.replace(tzinfo=self.tz)

    def convert(self, aware: datetime) -> datetime:
        return aware.astimezone() if self.tz is None else aware.astimezone(self.tz)

    def shift(self, when: datetime, **delta) -> datetime:
        """Add a wall-clock delta, recomputing the UTC offset (daylight saving)."""
        return self.localize(when.replace(tzinfo=None) + timedelta(**delta))

    def display(self) -> str:
        if self.tz is not None:
            return self.name
        env_tz = os.environ.get("TZ", "").lstrip(":")
        if env_tz:
            return env_tz
        real = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in real:
            return real.split("zoneinfo/", 1)[1]
        return datetime.now().astimezone().tzname() or "local"


def parse_iso(value: str, zone: Zone) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        return zone.localize(parsed)
    return zone.convert(parsed)


def get_now(zone: Zone) -> datetime:
    raw = os.environ.get("TODO_NOW")
    if raw:
        parsed = parse_iso(raw, zone)
        if parsed is None:
            raise TodoError(f"TODO_NOW={raw!r} is not an ISO 8601 date-time such as "
                            f"2026-11-11T07:30:00")
        return parsed
    return zone.convert(datetime.now(timezone.utc))


def iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def weekday(d: date) -> str:
    return WEEKDAYS[d.weekday()]


RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value: str | None) -> date | None:
    if not value or not RE_DATE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ------------------------------------------------------------------- workspace paths

def xdg_config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    return Path(value) if value else Path.home() / ".config"


def pointer_file() -> Path:
    return xdg_config_home() / "todo-skill" / "home"


def _abs(p: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(p)))


def resolve_home(arg: str | None = None) -> Path:
    """--home, then $TODO_HOME, then the pointer file, then ~/todo."""
    if arg:
        return _abs(arg)
    env = os.environ.get("TODO_HOME")
    if env:
        return _abs(env)
    text = read_text(pointer_file())
    if text:
        for line in split_lines(text):
            if line.strip():
                return _abs(line.strip())
    return Path.home() / "todo"


class Workspace:
    def __init__(self, home: Path):
        self.home = home
        self.config = home / "config.toml"
        self.todo = home / "TODO.md"
        self.log = home / "log.md"
        self.context = home / "context.md"
        self.briefs = home / "briefs"
        self.drafts = home / "drafts"
        self.subskills = home / "subskills"
        self.archive = home / "archive"
        self.state_dir = home / ".state"
        self.state = self.state_dir / "state.json"
        self.lock = self.state_dir / "run.lock"
        self.snapshot = self.state_dir / "snapshot.TODO.md"
        self.backups = self.state_dir / "backups"

    def brief(self, day: str) -> Path:
        return self.briefs / f"{day}.md"


TEMPLATES = {
    "config.toml": "config.example.toml",
    "TODO.md": "TODO.template.md",
    "log.md": "log.template.md",
    "context.md": "context.template.md",
}


def template_text(name: str) -> str:
    text = read_text(SKILL_DIR / "assets" / TEMPLATES[name])
    if text is None:
        raise TodoError(f"missing template assets/{TEMPLATES[name]} in the skill directory "
                        f"{SKILL_DIR}")
    return text


def workspace_for(args) -> Workspace:
    return Workspace(resolve_home(getattr(args, "home", None)))


def require_workspace(args) -> Workspace:
    ws = workspace_for(args)
    if not ws.home.is_dir() or not ws.config.is_file():
        raise TodoError(f"no workspace at {ws.home} (config.toml not found). Run "
                        f"`python3 {SKILL_DIR}/scripts/todo.py init` first, or point "
                        f"--home / $TODO_HOME at an existing workspace.")
    return ws


# ------------------------------------------------------------------------------ config

# kind: str | bool | int:<min> | num:<min> | strs | enum:a|b|c
CONFIG_SPEC: dict[str, dict[str, tuple[str, object]]] = {
    "run": {
        "timezone": ("str", "local"),
        "max_lookback_days": ("int:1", 7),
        "lock_stale_minutes": ("int:1", 90),
    },
    "intake": {
        "mode": ("enum:confirm-all|auto-high|auto-all", "auto-high"),
        "proposal_ttl_days": ("int:1", 7),
        "dismissed_keep_days": ("int:1", 21),
    },
    "focus": {
        "max_items": ("int:1", 5),
        "stale_after_days": ("int:1", 5),
        "due_soon_days": ("int:0", 3),
    },
    "history": {
        "log_keep_days": ("int:1", 7),
        "brief_keep_days": ("int:1", 7),
        "backup_keep": ("int:1", 14),
    },
    "automation": {
        "mode": ("enum:off|prepare", "prepare"),
        "max_per_run": ("int:0", 5),
        "allow_actions": ("strs", []),
    },
    "runner": {
        "agent": ("str", "claude"),
        "model": ("str", ""),
        "max_budget_usd": ("num:0", 0),
        "timeout_minutes": ("int:1", 30),
        "notify": ("bool", True),
        "retry_delay_seconds": ("int:0", 600),
        "extra_allowed_tools": ("strs", []),
    },
}

SUBSKILL_SPEC: dict[str, tuple[str, object]] = {
    "name": ("str", None),
    "enabled": ("bool", True),
    "path": ("str", ""),
    "window": ("enum:since-last-run|rolling", "since-last-run"),
    "lookback_days": ("int:1", None),
    "max_items": ("int:1", 15),
    "allowed_tools": ("strs", []),
}

RE_SUBSKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _check_kind(key: str, kind: str, value) -> str | None:
    """Return an error message, or None when value fits kind."""
    if kind == "str":
        return None if isinstance(value, str) else f"{key}: expected a string"
    if kind == "bool":
        return None if isinstance(value, bool) else f"{key}: expected true or false"
    if kind.startswith("int:"):
        low = int(kind[4:])
        if type(value) is not int:
            return f"{key}: expected a whole number"
        return None if value >= low else f"{key}: expected a whole number >= {low}"
    if kind.startswith("num:"):
        low = float(kind[4:])
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{key}: expected a number"
        return None if value >= low else f"{key}: expected a number >= {low:g}"
    if kind == "strs":
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        return None if ok else f"{key}: expected a list of strings"
    if kind.startswith("enum:"):
        options = kind[5:].split("|")
        if value in options:
            return None
        return f"{key}: expected one of " + ", ".join(f'"{o}"' for o in options)
    return None  # pragma: no cover


def load_config(ws: Workspace) -> tuple[dict, list[str]]:
    """Parse and validate config.toml. Raises TodoError(2) naming the offending key."""
    warnings: list[str] = []
    text = read_text(ws.config)
    if text is None:
        raise TodoError(f"cannot read {ws.config}")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TodoError(f"{ws.config}: not valid TOML: {exc}")

    errors: list[str] = []
    cfg: dict = {"schema": 1}

    known_top = {"schema", "subskills", *CONFIG_SPEC}
    for key in raw:
        if key not in known_top:
            warnings.append(f"config.toml: unknown key {key!r} ignored")
    if "schema" in raw and raw["schema"] != 1:
        errors.append(f"schema: only schema 1 is supported, found {raw['schema']!r}")

    for table, spec in CONFIG_SPEC.items():
        given = raw.get(table, {})
        if not isinstance(given, dict):
            errors.append(f"{table}: expected a table [{table}]")
            given = {}
        cfg[table] = {}
        for key, (kind, default) in spec.items():
            if key in given:
                problem = _check_kind(f"{table}.{key}", kind, given[key])
                if problem:
                    errors.append(problem)
                    cfg[table][key] = default
                else:
                    cfg[table][key] = given[key]
            else:
                cfg[table][key] = list(default) if isinstance(default, list) else default
        for key in given:
            if key not in spec:
                warnings.append(f"config.toml: unknown key {table}.{key} ignored")

    run, focus, history = cfg["run"], cfg["focus"], cfg["history"]
    if not errors:
        try:
            Zone(run["timezone"])
        except TodoError as exc:
            errors.append(exc.message)
    if focus["stale_after_days"] > history["log_keep_days"]:
        warnings.append(
            f"focus.stale_after_days ({focus['stale_after_days']}) is greater than "
            f"history.log_keep_days ({history['log_keep_days']}); the log cannot show that "
            f"many days, so it was clamped to {history['log_keep_days']}")
        focus["stale_after_days"] = history["log_keep_days"]

    for entry in cfg["automation"]["allow_actions"]:
        if not re.match(r"^[a-z0-9][a-z0-9-]*\.[A-Za-z_][A-Za-z0-9_]*$", entry):
            errors.append(f"automation.allow_actions: {entry!r} must look like "
                          f"\"<subskill>.<action>\", e.g. \"gmail.create_draft\"")

    cfg["subskills"] = []
    subs = raw.get("subskills", [])
    if not isinstance(subs, list) or not all(isinstance(s, dict) for s in subs):
        errors.append("subskills: expected [[subskills]] entries (an array of tables)")
        subs = []
    seen: set[str] = set()
    for index, given in enumerate(subs, 1):
        label = f"subskills[{index}]"
        entry: dict = {}
        name = given.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}.name: required, a string such as \"gmail\"")
            name = None
        else:
            label = f"subskills[{index}] ({name})"
            if not RE_SUBSKILL_NAME.match(name):
                errors.append(f"{label}.name: must match ^[a-z0-9][a-z0-9-]*$ (lowercase "
                              f"letters, digits, hyphens; no leading hyphen or underscore)")
            elif name in RESERVED_SUBSKILLS:
                errors.append(f"{label}.name: {name!r} is reserved; it is a procedure for "
                              f"the agent, not a source of data")
            elif name in seen:
                errors.append(f"{label}.name: duplicate subskill name {name!r}")
            seen.add(name)
        entry["name"] = name
        for key, (kind, default) in SUBSKILL_SPEC.items():
            if key == "name":
                continue
            if key in given:
                problem = _check_kind(f"{label}.{key}", kind, given[key])
                if problem:
                    errors.append(problem)
                    entry[key] = default
                else:
                    entry[key] = given[key]
            else:
                entry[key] = list(default) if isinstance(default, list) else default
        params = given.get("params", {})
        if not isinstance(params, dict):
            errors.append(f"{label}.params: expected a table [subskills.params]")
            params = {}
        entry["params"] = params
        for key in given:
            if key not in SUBSKILL_SPEC and key != "params":
                warnings.append(f"config.toml: unknown key {label}.{key} ignored")
        if entry["lookback_days"] is None:
            entry["lookback_days"] = run["max_lookback_days"]
        elif entry["window"] == "rolling" and entry["lookback_days"] > history["log_keep_days"]:
            warnings.append(
                f"{label}.lookback_days ({entry['lookback_days']}) is greater than "
                f"history.log_keep_days ({history['log_keep_days']}): the log will have "
                f"forgotten items that old, so closed tasks may be reported again")
        cfg["subskills"].append(entry)

    if errors:
        raise TodoError("config.toml has problems:\n  " + "\n  ".join(errors))

    unattended_unsafe = re.compile(r"(send|reply|accept|decline|post|share|pay|delete|forward)")
    names = {s["name"] for s in cfg["subskills"]}
    for entry in cfg["automation"]["allow_actions"]:
        sub, _, action = entry.partition(".")
        if unattended_unsafe.search(action.lower()):
            warnings.append(
                f"automation.allow_actions: {entry!r} sounds like an action that reaches "
                f"other people or cannot be undone; the skill never runs those unattended "
                f"whatever the config says")
        if sub not in names:
            warnings.append(f"automation.allow_actions: {entry!r} names a subskill that is "
                            f"not listed in [[subskills]]")
    return cfg, warnings


def resolve_subskills(ws: Workspace, cfg: dict) -> tuple[list[dict], list[str]]:
    """Enabled subskills whose SKILL.md can be found, plus warnings for the rest."""
    found, warnings = [], []
    for entry in cfg["subskills"]:
        if not entry["enabled"]:
            continue
        name = entry["name"]
        skill_file, origin = None, None
        if entry["path"]:
            p = _abs(entry["path"]) if entry["path"].startswith(("/", "~")) \
                else Path(os.path.abspath(ws.home / entry["path"]))
            cand = p / "SKILL.md" if p.is_dir() else p
            if cand.is_file():
                skill_file, origin = cand, "path"
            else:
                warnings.append(f"subskill {name}: path {entry['path']!r} does not lead to "
                                f"a SKILL.md; it is left out of this run")
        else:
            for base, tag in ((ws.subskills, "workspace"), (SKILL_DIR / "subskills", "builtin")):
                cand = base / name / "SKILL.md"
                if cand.is_file():
                    skill_file, origin = cand, tag
                    break
            if skill_file is None:
                warnings.append(f"subskill {name}: no SKILL.md in {ws.subskills / name} or "
                                f"{SKILL_DIR / 'subskills' / name}; it is left out of this run")
        if skill_file is not None:
            found.append({"entry": entry, "name": name, "origin": origin,
                          "skill_file": skill_file, "dir": skill_file.parent})
    return found, warnings


def expand_placeholders(rule: str, ws: Workspace, subskill_dir: Path | None) -> str:
    rule = rule.replace("{skill}", str(SKILL_DIR)).replace("{home}", str(ws.home))
    if subskill_dir is not None:
        rule = rule.replace("{subskill_dir}", str(subskill_dir))
    return rule


def allowed_tools(ws: Workspace, cfg: dict) -> tuple[list[str], list[str]]:
    resolved, warnings = resolve_subskills(ws, cfg)
    rules: list[str] = []
    for sub in resolved:
        for rule in sub["entry"]["allowed_tools"]:
            rules.append(expand_placeholders(rule, ws, sub["dir"]))
    for rule in cfg["runner"]["extra_allowed_tools"]:
        rules.append(expand_placeholders(rule, ws, None))
    unique = list(dict.fromkeys(r for r in rules if r.strip()))
    return unique, warnings


# ------------------------------------------------------------------------------ state

def default_state() -> dict:
    return {"schema": STATE_SCHEMA, "last_run": None, "sources": {},
            "next_id": {"T": 1, "G": 1}}


def load_state(ws: Workspace) -> tuple[dict, list[str]]:
    state, warnings = default_state(), []
    text = read_text(ws.state)
    if text is None:
        return state, warnings
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
    except ValueError as exc:
        warnings.append(f".state/state.json is unreadable ({exc}); treated as a first run. "
                        f"The id counter was rebuilt from TODO.md.")
        return state, warnings
    if isinstance(raw.get("last_run"), dict):
        state["last_run"] = raw["last_run"]
    if isinstance(raw.get("sources"), dict):
        state["sources"] = {k: v for k, v in raw["sources"].items() if isinstance(v, dict)}
    if isinstance(raw.get("next_id"), dict):
        for k in ("T", "G"):
            v = raw["next_id"].get(k)
            if type(v) is int and v >= 1:
                state["next_id"][k] = v
    return state, warnings


def save_state(ws: Workspace, state: dict) -> None:
    write_atomic(ws.state, json.dumps(state, indent=2, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------- TODO.md model

class Issue:
    __slots__ = ("file", "line", "code", "message")

    def __init__(self, file: str, line: int, code: str, message: str):
        self.file, self.line, self.code, self.message = file, line, code, message

    @property
    def is_error(self) -> bool:
        return self.code.startswith("E")

    def text(self) -> str:
        return f"{self.file}:{self.line}: {self.code} {self.message}"

    def as_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "code": self.code,
                "message": self.message}


RE_COMMENT = re.compile(r"^\s*<!--.*-->\s*$")
RE_PRIO = re.compile(r"^P([0-3])([!?])?$")
RE_TASK_ID = re.compile(r"^T(\d+)$")
RE_FIELD = re.compile(r"^([A-Za-z][A-Za-z_-]*):(?: (.*))?$")
RE_TASKISH = re.compile(r"^\s*- ?\[.?\]")
RE_TASK_LINE = re.compile(r"^(\s*)- \[(.)\] (.*)$")
RE_GOAL_HEAD = re.compile(r"^### (\S.*)$")
RE_SUB_HEAD = re.compile(r"^#### (\S.*)$")
RE_GOAL_ID = re.compile(r"^G(\d+)$")
RE_SUB_ID = re.compile(r"^G(\d+)\.(\d+)$")
RE_DISMISSED = re.compile(r"^- (.+?) \| dismissed: (\S+) \| why: (.+)$")
RE_ID_SCAN_TASK = re.compile(r"^\s*- \[.\]\s+T(\d+)\b")
RE_ID_SCAN_GOAL = re.compile(r"^#{3,4} G(\d+)\b")

SECTION_LIST = ", ".join(f"## {s}" for s in SECTIONS)


class ParsedTodo:
    def __init__(self):
        self.lines: list[str] = []
        self.tasks: list[dict] = []
        self.goals: list[dict] = []      # goals and subgoals
        self.dismissed: list[dict] = []
        self.unparsed: list[dict] = []
        self.issues: list[Issue] = []
        self.sections: dict[str, int] = {}

    def add(self, line: int, code: str, message: str) -> None:
        self.issues.append(Issue("TODO.md", line, code, message))


def _parse_fields(parts: list[str], line: int, out: ParsedTodo, label: str) -> tuple[dict, bool]:
    """Parse 'key: value' parts. Returns (fields, structurally_ok)."""
    fields: dict[str, str] = {}
    ok = True
    for part in parts:
        m = RE_FIELD.match(part.strip())
        if not m:
            out.add(line, "E103",
                    f"{label}: {part.strip()!r} is not a 'key: value' field. Fields are "
                    f"separated by ' | ' and a title cannot contain ' | ' itself.")
            ok = False
            continue
        key, value = m.group(1), (m.group(2) or "").strip()
        if not value:
            out.add(line, "E103", f"{label}: field '{key}:' has no value; write "
                                  f"'{key}: <value>' or remove it")
            ok = False
            continue
        fields[key] = value
    return fields, ok


def _check_keys(fields: dict, allowed: set[str], line: int, out: ParsedTodo, label: str) -> None:
    for key, value in fields.items():
        if key not in allowed:
            out.add(line, "E105", f"{label}: unknown field '{key}'. Known fields: "
                                  f"{', '.join(sorted(allowed))}")
        elif key in DATE_KEYS and parse_date(value) is None:
            out.add(line, "E106", f"{label}: '{key}: {value}' is not a date; expected "
                                  f"YYYY-MM-DD, e.g. 2026-11-13")


def parse_todo(text: str) -> ParsedTodo:
    out = ParsedTodo()
    lines = split_lines(text)
    out.lines = lines
    section: str | None = None
    last_idx = -1
    goal_id: str | None = None
    sub_id: str | None = None
    parent: str | None = None
    prev_was_goal = False

    def unparsed(n: int, raw: str) -> None:
        out.unparsed.append({"line": n, "section": section, "text": raw})

    for n, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if len(line) > 300:
            out.add(n, "E108", f"line is {len(line)} characters; the limit is 300. Shorten "
                               f"the title and move detail out (one short 'note:' at most).")
        if not line.strip() or RE_COMMENT.match(line):
            continue
        if line == "# TODO":
            continue

        # --- ## sections
        if line.startswith("## "):
            name = line[3:].strip()
            section, goal_id, sub_id, parent, prev_was_goal = name, None, None, None, False
            if name in SECTIONS:
                idx = SECTIONS.index(name)
                if name in out.sections:
                    out.add(n, "E101", f"section '## {name}' appears twice (first at line "
                                       f"{out.sections[name]}); each section must appear once")
                else:
                    out.sections[name] = n
                    if idx < last_idx:
                        out.add(n, "E101", f"section '## {name}' is out of order; the order "
                                           f"is: {SECTION_LIST}")
                last_idx = max(last_idx, idx)
            else:
                out.add(n, "E101", f"unknown section '## {name}'; the only sections are: "
                                   f"{SECTION_LIST}")
            continue

        if section is None:
            out.add(n, "E111", f"line outside any section; expected it under one of the "
                               f"sections {SECTION_LIST}")
            unparsed(n, line)
            continue

        # --- goal / subgoal headings
        if line.startswith("#### ") or line.startswith("### "):
            is_sub = line.startswith("#### ")
            body = line[5:] if is_sub else line[4:]
            parts = body.split(" | ")
            gid = parts[0].strip()
            kind = "subgoal" if is_sub else "goal"
            usage = ("#### G<n>.<m> | <title> [| P<0-3>[!]] [| due: YYYY-MM-DD]" if is_sub
                     else "### G<n> | <title> | P<0-3>[!] [| due: YYYY-MM-DD]")
            m = RE_SUB_ID.match(gid) if is_sub else RE_GOAL_ID.match(gid)
            if not m:
                out.add(n, "E102", f"malformed {kind} heading: expected '{usage}', but the "
                                   f"id {gid!r} is not "
                                   f"{'G<n>.<m>, e.g. G1.1' if is_sub else 'G<n>, e.g. G1'}")
                unparsed(n, line)
                prev_was_goal = False
                continue
            if len(parts) < 2 or not parts[1].strip():
                out.add(n, "E102", f"malformed {kind} heading: expected '{usage}'; the title "
                                   f"is missing")
                unparsed(n, line)
                prev_was_goal = False
                continue
            title = parts[1].strip()
            rest = parts[2:]
            prio = None
            if rest and RE_PRIO.match(rest[0].strip()):
                prio = rest[0].strip()
                rest = rest[1:]
            if prio is not None and prio.endswith("?"):
                out.add(n, "E102", f"malformed {kind} heading: priority '{prio}' cannot be "
                                   f"provisional; use P<0-3> or P<0-3>!")
                unparsed(n, line)
                prev_was_goal = False
                continue
            if prio is None and not is_sub:
                out.add(n, "E102", f"malformed goal heading: expected '{usage}'; the "
                                   f"priority P0-P3 after the title is missing")
                unparsed(n, line)
                prev_was_goal = False
                continue
            fields, ok = _parse_fields(rest, n, out, f"{gid}")
            if not ok:
                # bad field syntax on a heading is a heading problem
                out.issues = [i for i in out.issues
                              if not (i.line == n and i.code == "E103")]
                out.add(n, "E102", f"malformed {kind} heading: expected '{usage}'; "
                                   f"after the title come only P<0-3> and 'key: value' fields")
                unparsed(n, line)
                prev_was_goal = False
                continue
            if section not in ("Goals", "Parked"):
                out.add(n, "E102", f"{kind} heading {gid} is under '## {section}'; goals "
                                   f"and subgoals belong only under '## Goals' or '## Parked'")
            if is_sub:
                if goal_id is None or goal_id != f"G{m.group(1)}":
                    out.add(n, "E102", f"subgoal {gid} must sit under its parent goal "
                                       f"G{m.group(1)} (put it after that goal's heading and "
                                       f"before the next '### G' heading)")
                sub_id = gid
            else:
                goal_id, sub_id = gid, None
            _check_keys(fields, GOAL_KEYS, n, out, gid)
            out.goals.append({"id": gid, "title": title, "priority": prio, "fields": fields,
                              "line": n, "section": section, "subgoal": is_sub,
                              "parent": goal_id if is_sub else None})
            parent = None
            prev_was_goal = not is_sub
            continue

        if line.startswith("> ") and prev_was_goal:
            if len(line) > 200:
                out.add(n, "E108", f"'Done when' line is {len(line)} characters; the limit "
                                   f"is 200. Keep it to one short sentence.")
            prev_was_goal = False
            continue

        prev_was_goal = False

        # --- Dismissed section
        if section == "Dismissed":
            m = RE_DISMISSED.match(line)
            if not m:
                out.add(n, "E112", "malformed Dismissed line: expected "
                                   "'- <source reference> | dismissed: YYYY-MM-DD | why: "
                                   "<short reason>'")
                unparsed(n, line)
                continue
            d = parse_date(m.group(2))
            if d is None:
                out.add(n, "E106", f"'dismissed: {m.group(2)}' is not a date; expected "
                                   f"YYYY-MM-DD, e.g. 2026-11-11")
            out.dismissed.append({"ref": m.group(1), "date": d, "why": m.group(3),
                                  "line": n})
            continue

        # --- tasks
        if RE_TASKISH.match(line):
            m = RE_TASK_LINE.match(line)
            if not m:
                out.add(n, "E103", f"malformed task line: expected '{TASK_FORMAT}' with "
                                   f"'- [ ] ' (dash, space, [ ], space) at the start")
                unparsed(n, line)
                continue
            indent, box, rest = m.group(1), m.group(2), m.group(3)
            problems = []
            if indent not in ("", "  "):
                problems.append(f"indentation must be 0 or 2 spaces (2 spaces = sub-task), "
                                f"found {len(indent)} {'tab/space characters' if chr(9) in indent else 'spaces'}")
            if box not in (" ", "x", "-"):
                problems.append(f"checkbox must be '[ ]' (open), '[x]' (done) or '[-]' "
                                f"(dropped), found '[{box}]'")
            parts = rest.split(" | ")
            tid = RE_TASK_ID.match(parts[0].strip())
            if not tid:
                problems.append(f"expected a task id T<n> right after the checkbox, found "
                                f"{parts[0].strip()!r}. If this is a note you typed, "
                                f"give it the next free id and 'src: user'")
            prio = None
            if len(parts) < 2 or not RE_PRIO.match(parts[1].strip()):
                problems.append("expected a priority P0, P1, P2 or P3 (optionally with ! or "
                                "?) as the second ' | ' field")
            else:
                prio = parts[1].strip()
            if len(parts) < 3 or not parts[2].strip():
                problems.append("expected a title as the third ' | ' field")
            if problems:
                out.add(n, "E103", f"malformed task line: {'; '.join(problems)}. "
                                   f"Expected '{TASK_FORMAT}'")
                unparsed(n, line)
                continue
            tid_s = parts[0].strip()
            fields, ok = _parse_fields(parts[3:], n, out, tid_s)
            if not ok:
                unparsed(n, line)
                continue
            if indent == "  ":
                if parent is None:
                    out.add(n, "E103", f"sub-task {tid_s} has no parent: a sub-task (two "
                                       f"leading spaces) must follow the task it belongs to "
                                       f"within the same section")
                    unparsed(n, line)
                    continue
                task_parent = parent
            else:
                task_parent = None
                parent = tid_s
            _check_keys(fields, TASK_KEYS, n, out, tid_s)
            out.tasks.append({
                "id": tid_s, "state": box, "priority": prio, "title": parts[2].strip(),
                "fields": fields, "line": n, "section": section, "indent": len(indent),
                "parent": task_parent, "goal": goal_id, "subgoal": sub_id,
                "raw": line,
            })
            continue

        if line.startswith("> "):
            out.add(n, "E111", "a '> Done when: …' line is only allowed directly under a "
                               "goal heading (###), and only one per goal")
        else:
            out.add(n, "E111", f"unrecognised line. If it is a to-do you typed, rewrite it "
                               f"as '{TASK_FORMAT}' (next free id from `todo.py begin`); "
                               f"otherwise remove it, because TODO.md holds only goals and "
                               f"tasks")
        unparsed(n, line)

    for name in SECTIONS:
        if name not in out.sections:
            out.add(0, "E101", f"missing section '## {name}'; all five sections must exist, "
                               f"in this order: {SECTION_LIST}")
    return out


def is_open(task: dict) -> bool:
    return task["state"] == " " and task["section"] in OPEN_SECTIONS


def scan_ids(text: str) -> tuple[set[str], int, int]:
    """Lenient id scan that survives malformed lines: task ids, max T, max G."""
    tasks: set[str] = set()
    max_t = max_g = 0
    for raw in split_lines(text):
        m = RE_ID_SCAN_TASK.match(raw)
        if m:
            tasks.add(f"T{int(m.group(1))}")
            max_t = max(max_t, int(m.group(1)))
        g = RE_ID_SCAN_GOAL.match(raw)
        if g:
            max_g = max(max_g, int(g.group(1)))
    return tasks, max_t, max_g


# ------------------------------------------------------------------------- log.md model

RE_LOG_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2}) (Mon|Tue|Wed|Thu|Fri|Sat|Sun)$")
RE_LOG_BULLET = re.compile(r"^- ([A-Za-z]+): (\S.*)$")
RE_BARE_ID_ITEM = re.compile(r"^(T\d+)\s*(?:\(.*)?$")   # an id with no title after it


class ParsedLog:
    def __init__(self):
        self.entries: list[dict] = []   # valid-date entries in file order
        self.issues: list[Issue] = []
        self.lines: list[str] = []

    def add(self, line: int, code: str, message: str) -> None:
        self.issues.append(Issue("log.md", line, code, message))


def parse_log(text: str) -> ParsedLog:
    out = ParsedLog()
    lines = split_lines(text)
    out.lines = lines
    cur: dict | None = None
    prev_date: date | None = None
    for n, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if not line.strip() or RE_COMMENT.match(line) or line == "# Log":
            continue
        if line.startswith("## "):
            m = RE_LOG_HEAD.match(line)
            d = parse_date(m.group(1)) if m else None
            cur = {"date": d, "line": n, "end": len(lines), "bullets": [], "text": "",
                   "verbs": {}}
            if not m or d is None:
                out.add(n, "E201", f"malformed entry heading {line!r}: expected "
                                   f"'## YYYY-MM-DD Ddd', e.g. '## 2026-11-11 Wed' "
                                   f"(Mon Tue Wed Thu Fri Sat Sun)")
                cur["date"] = None
            elif weekday(d) != m.group(2):
                out.add(n, "E201", f"weekday {m.group(2)} does not match {m.group(1)}, "
                                   f"which is a {weekday(d)}; expected "
                                   f"'## {m.group(1)} {weekday(d)}'")
            if cur["date"] is not None:
                if prev_date is not None and cur["date"] >= prev_date:
                    why = "is a duplicate of the entry above (merge same-day runs into " \
                          "one entry)" if cur["date"] == prev_date else \
                          "is newer than the entry above"
                    out.add(n, "E201", f"entry {cur['date'].isoformat()} {why}; entries "
                                       f"must be strictly newest first")
                prev_date = cur["date"]
                if out.entries:
                    out.entries[-1]["end"] = n - 1
                out.entries.append(cur)
            continue
        if line.startswith("# "):
            out.add(n, "E201", f"unexpected heading {line!r}: expected the title '# Log' "
                               f"once, then entries '## YYYY-MM-DD Ddd'")
            continue
        if cur is None:
            out.add(n, "E201", "expected an entry heading '## YYYY-MM-DD Ddd' before this "
                               "line")
            continue
        m = RE_LOG_BULLET.match(line)
        if not m or m.group(1) not in VERBS:
            out.add(n, "E202", f"bullet must be '- <verb>: <items>' with a verb from "
                               f"{', '.join(VERBS)} (lower case); found {line!r}")
            continue
        verb = m.group(1)
        if len(line) > 500:
            out.add(n, "E204", f"bullet is {len(line)} characters; the limit is 500. Keep "
                               f"only ids and short titles, or drop the least useful items.")
        if verb in cur["verbs"]:
            out.add(n, "E203", f"verb '{verb}' appears twice in the entry for "
                               f"{cur['date'] or 'this heading'} (first at line "
                               f"{cur['verbs'][verb]}); merge them into one bullet, items "
                               f"separated by '; '")
        else:
            cur["verbs"][verb] = n
        if verb in ("done", "dropped"):
            for item in m.group(2).split("; "):
                bare = RE_BARE_ID_ITEM.match(item.strip())
                if bare:
                    out.add(n, "E205", f"'{verb}: {bare.group(1)}' has no title; write "
                                       f"'{bare.group(1)} <title>' (the title is in the "
                                       f"pre-run TODO.md or in user_edits). Titles are how "
                                       f"a source item that comes up again is recognised "
                                       f"as already closed.")
        cur["bullets"].append({"verb": verb, "text": m.group(2), "line": n})
        cur["text"] += "\n" + line
    return out


def mentions(entry_text: str, tid: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(tid)}(?![\w])", entry_text) is not None


# -------------------------------------------------------------------------------- lint

def lint_todo(parsed: ParsedTodo, ws: Workspace, state: dict,
              in_run: bool = False) -> list[Issue]:
    issues = list(parsed.issues)

    def add(line: int, code: str, msg: str) -> None:
        issues.append(Issue("TODO.md", line, code, msg))

    seen: dict[str, int] = {}
    for item in parsed.goals + parsed.tasks:
        if item["id"] in seen:
            add(item["line"], "E104", f"duplicate id {item['id']} (first used at line "
                                      f"{seen[item['id']]}); ids are never reused, so give "
                                      f"this one the next free id")
        else:
            seen[item["id"]] = item["line"]

    open_count = 0
    proposals = 0
    for t in parsed.tasks:
        f, sec, line = t["fields"], t["section"], t["line"]
        if "src" not in f:
            add(line, "E107", f"{t['id']} has no 'src:' field; add "
                              f"'| src: user' or '| src: <subskill> \"<label>\" <date>' "
                              f"so the task can be traced to where it came from")
        if t["state"] in ("x", "-"):
            what = "done" if t["state"] == "x" else "dropped"
            add(line, "E110", f"{t['id']} is still marked [{t['state']}]; log it under "
                              f"'{what}:' in today's log entry and delete the line")
        prio = t["priority"]
        if prio.endswith("?") and sec != "Proposed":
            add(line, "E109", f"{t['id']} has the provisional priority {prio} but is under "
                              f"'## {sec}'; '?' is only for '## Proposed'. Remove the '?' "
                              f"(accepted) or move the task to ## Proposed")
        if sec == "Proposed":
            if not prio.endswith("?"):
                add(line, "E109", f"{t['id']} is under '## Proposed' but its priority "
                                  f"{prio} has no '?'; expected e.g. P2?")
            if "proposed" not in f:
                add(line, "E109", f"{t['id']} is under '## Proposed' but has no "
                                  f"'proposed: YYYY-MM-DD' field")
            proposals += 1
        elif "proposed" in f:
            add(line, "E109", f"{t['id']} has 'proposed:' but is under '## {sec}'; that "
                              f"field belongs only in '## Proposed' (remove it when a "
                              f"proposal is accepted)")
        if is_open(t):
            open_count += 1
        if "draft" in f:
            target = Path(f["draft"])
            target = target if target.is_absolute() else ws.home / target
            if not target.exists():
                add(line, "W122", f"{t['id']}: draft file {f['draft']!r} does not exist "
                                  f"(paths are relative to the workspace)")
    if proposals > 15:
        add(0, "W120", f"{proposals} proposals are waiting (more than 15); ask the user to "
                       f"accept or reject some, or let them expire")
    if open_count > 60:
        add(0, "W121", f"{open_count} open tasks (more than 60); the list is too long to "
                       f"steer by. Suggest parking or dropping some")

    for g in parsed.goals:
        if g["section"] == "Goals" and not g["subgoal"]:
            has_open = any(t["state"] == " " and t["goal"] == g["id"] for t in parsed.tasks)
            if not has_open:
                add(g["line"], "W123", f"goal {g['id']} has no open task; add a task with a "
                                       f"concrete 'next:' or park the goal")

    counters = state.get("next_id", {"T": 1, "G": 1})
    if in_run or not ws.state.is_file():
        # During a run every id issued from `begin` is at or above the counter by design,
        # and `begin` already accounts for hand-typed ids; before the first finish there
        # is no counter at all.
        counters = {"T": 0, "G": 0}
    for t in parsed.tasks:
        if counters["T"] and num(t["id"]) >= counters["T"]:
            add(t["line"], "W124", f"id {t['id']} is at or above the next_id counter "
                                   f"T={counters['T']}; `finish` will bump the counter")
    for g in parsed.goals:
        gnum = int(re.match(r"G(\d+)", g["id"]).group(1))
        if counters["G"] and gnum >= counters["G"]:
            add(g["line"], "W124", f"id {g['id']} is at or above the next_id counter "
                                   f"G={counters['G']}; `finish` will bump the counter")
    return issues


def lint_log(parsed: ParsedLog, cfg: dict) -> list[Issue]:
    issues = list(parsed.issues)
    keep = cfg["history"]["log_keep_days"]
    if len(parsed.entries) > keep:
        first_extra = parsed.entries[keep]["line"]
        issues.append(Issue("log.md", first_extra, "W210",
                            f"{len(parsed.entries)} entries; `finish` keeps the newest "
                            f"{keep} (history.log_keep_days) and moves the rest to archive/"))
    return issues


def lint_brief(text: str, day: str) -> list[Issue]:
    name = f"briefs/{day}.md"
    issues: list[Issue] = []
    lines = split_lines(text)
    d = parse_date(day)
    expected = f"# Daily brief | {day} {weekday(d)}" if d else f"# Daily brief | {day}"
    first = lines[0].rstrip() if lines else ""
    if first != expected:
        issues.append(Issue(name, 1, "E401", f"first line must be {expected!r}; found "
                                             f"{first!r}"))
    headings = [(i, l[3:].strip()) for i, l in enumerate(lines, 1) if l.startswith("## ")]
    names = [h for _, h in headings]
    pos = -1
    for req in BRIEF_REQUIRED:
        if req not in names:
            issues.append(Issue(name, 0, "E402", f"required section '## {req}' is missing; "
                                                 f"required sections, in order: "
                                                 + ", ".join(f"## {r}" for r in BRIEF_REQUIRED)
                                                 + " (write 'Nothing.' under an empty one)"))
            continue
        idx = names.index(req)
        if idx < pos:
            issues.append(Issue(name, headings[idx][0], "E402",
                                f"section '## {req}' is out of order; required sections "
                                f"come in this order: "
                                + ", ".join(f"## {r}" for r in BRIEF_REQUIRED)))
        pos = max(pos, idx)
    if len(lines) > 100:
        issues.append(Issue(name, len(lines), "W410", f"brief has {len(lines)} lines; aim "
                                                      f"for one screen, 100 lines at most"))
    return issues


def lint_context(text: str) -> list[Issue]:
    n = sum(1 for l in split_lines(text) if l.strip())
    if n > 40:
        return [Issue("context.md", 0, "W501", f"{n} non-blank lines; keep it to 40 or "
                                               f"fewer so every run can afford to read it")]
    return []


def finish_checks(ws: Workspace, lock: dict, todo_text: str, log: ParsedLog) -> list[Issue]:
    """E301-E303, exactly as `finish` applies them."""
    issues: list[Issue] = []
    run_date = lock.get("run_date", "")
    backup = Path(lock.get("backup_dir", ""))
    before_text = read_text(backup / "TODO.md") if lock.get("backup_dir") else None
    entry = next((e for e in log.entries
                  if e["date"] is not None and e["date"].isoformat() == run_date), None)
    entry_text = entry["text"] if entry else ""
    if before_text is None:
        note(f"cannot compare ids: backup {backup / 'TODO.md'} is missing")
    else:
        before, _, _ = scan_ids(before_text)
        now_ids, _, _ = scan_ids(todo_text)
        # The baseline is TODO.md as the skill last left it (the snapshot saved with the
        # backup), so tasks the user added or deleted by hand since then are held to the
        # same rule as tasks this run touched. Without a snapshot, the run's start is it.
        snap_text = read_text(backup / "snapshot.TODO.md")
        known = scan_ids(snap_text)[0] if snap_text is not None else before
        where = (f"today's log entry (## {run_date} {weekday(date.fromisoformat(run_date))})"
                 if entry else f"a log entry for {run_date}, which does not exist yet")
        for tid in sorted((before | known) - now_ids, key=num):
            if not mentions(entry_text, tid):
                issues.append(Issue("finish", 0, "E301",
                                    f"{tid} was in TODO.md after the last finished run (or "
                                    f"when this one began) and is gone, but {where} does "
                                    f"not mention it. Add it to the 'done:' or 'dropped:' "
                                    f"bullet (e.g. '{tid} <title>'; if the user deleted the "
                                    f"line by hand: '{tid} <title> (removed by user)')"))
        for tid in sorted(now_ids - known, key=num):
            if not mentions(entry_text, tid):
                issues.append(Issue("finish", 0, "E302",
                                    f"{tid} is new in TODO.md since the last finished run, "
                                    f"but {where} does not mention it. Add it to the "
                                    f"'added:' bullet (e.g. '{tid} <title> (<source>)'; if "
                                    f"the user typed it: '{tid} <title> (user)')"))
    if lock.get("mode") == "daily" and not ws.brief(run_date).is_file():
        issues.append(Issue("finish", 0, "E303",
                            f"no brief for {run_date}; write briefs/{run_date}.md (format: "
                            f"references/state-format.md)"))
    return issues


def collect_issues(ws: Workspace, cfg: dict, state: dict, lock: dict | None,
                   today: str) -> tuple[list[Issue], str, ParsedLog]:
    issues: list[Issue] = []
    todo_text = read_text(ws.todo)
    if todo_text is None:
        issues.append(Issue("TODO.md", 0, "E101", "TODO.md is missing; `todo.py begin` "
                                                  "recreates it from the template"))
        todo_text = ""
    else:
        issues += lint_todo(parse_todo(todo_text), ws, state,
                            in_run=bool(lock and lock.get("backup_dir")))
    log_text = read_text(ws.log)
    log = parse_log(log_text or "")
    if log_text is not None:
        issues += lint_log(log, cfg)
    ctx_text = read_text(ws.context)
    if ctx_text is not None:
        issues += lint_context(ctx_text)
    brief_day = lock["run_date"] if lock and lock.get("run_date") else today
    brief_text = read_text(ws.brief(brief_day))
    if brief_text is not None:
        issues += lint_brief(brief_text, brief_day)
    if lock and lock.get("backup_dir"):
        issues += finish_checks(ws, lock, todo_text, log)
    return issues, todo_text, log


# ------------------------------------------------------------------------------- lock

def read_lock(ws: Workspace) -> dict | None:
    text = read_text(ws.lock)
    if text is None:
        return None
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return {"corrupt": True, "mode": "unknown"}
    return data


def lock_is_stale(ws: Workspace, lock: dict, cfg: dict, now: datetime, zone: Zone) -> bool:
    limit = cfg["run"]["lock_stale_minutes"]
    if lock.get("mode") == "interactive":
        limit = min(limit, 15)
    started = parse_iso(lock.get("started", ""), zone) if not lock.get("corrupt") else None
    if started is None:
        try:
            started = zone.convert(datetime.fromtimestamp(ws.lock.stat().st_mtime, timezone.utc))
        except OSError:
            return True
    return (now - started) > timedelta(minutes=limit)


def describe_lock(lock: dict, now: datetime, zone: Zone) -> str:
    started = parse_iso(lock.get("started", ""), zone)
    if started is None:
        return f"a {lock.get('mode', 'unknown')} run (start time unknown)"
    mins = int((now - started).total_seconds() // 60)
    return (f"a {lock.get('mode', 'unknown')} run since {iso(started)} "
            f"({mins} minute{'s' if mins != 1 else ''} ago)")


def make_backup(ws: Workspace, now: datetime) -> Path:
    base = now.strftime("%Y%m%d-%H%M%S")
    ws.backups.mkdir(parents=True, exist_ok=True)
    target, k = ws.backups / base, 1
    while True:
        try:
            target.mkdir()
            break
        except FileExistsError:
            k += 1
            target = ws.backups / f"{base}-{k:02d}"
    for name, src in (("TODO.md", ws.todo), ("log.md", ws.log), ("state.json", ws.state),
                      ("snapshot.TODO.md", ws.snapshot)):
        if src.is_file():
            shutil.copy2(src, target / name)
        elif name == "state.json":
            (target / name).write_text("{}\n", encoding="utf-8")
    return target


def list_backups(ws: Workspace) -> list[Path]:
    if not ws.backups.is_dir():
        return []
    return sorted((p for p in ws.backups.iterdir() if p.is_dir()), key=lambda p: p.name)


# --------------------------------------------------------------------------- commands

def cmd_home(args) -> int:
    print(resolve_home(getattr(args, "home", None)))
    return EXIT_OK


def cmd_init(args) -> int:
    ws = workspace_for(args)
    created, skipped = [], []
    ws.home.mkdir(parents=True, exist_ok=True)
    for d in ("briefs", "drafts", "subskills", "archive", "notes", ".state/backups"):
        p = ws.home / d
        (skipped if p.is_dir() else created).append(d + "/")
        p.mkdir(parents=True, exist_ok=True)
    for name in TEMPLATES:
        p = ws.home / name
        if p.exists():
            skipped.append(name)
        else:
            write_atomic(p, template_text(name))
            created.append(name)
    default_set = False
    if args.set_default:
        write_atomic(pointer_file(), str(ws.home) + "\n")
        default_set = True
    emit({"home": str(ws.home), "created": created, "skipped": skipped,
          "default_set": default_set,
          "pointer_file": str(pointer_file()) if default_set else None})
    return EXIT_OK


def newest_brief_before(ws: Workspace, today: date) -> Path | None:
    best: tuple[date, Path] | None = None
    if ws.briefs.is_dir():
        for p in ws.briefs.iterdir():
            m = re.match(r"^(\d{4}-\d{2}-\d{2})\.md$", p.name)
            d = parse_date(m.group(1)) if m else None
            if d and d < today and (best is None or d > best[0]):
                best = (d, p)
    return best[1] if best else None


def window_for(entry: dict, src_state: dict, cfg: dict, now: datetime, zone: Zone) -> dict:
    max_back = zone.shift(now, days=-cfg["run"]["max_lookback_days"])
    if entry["window"] == "rolling":
        since = zone.shift(now, days=-entry["lookback_days"])
    else:
        last = parse_iso(src_state.get("last_success", ""), zone) if src_state.get(
            "last_success") else None
        since = max(last, max_back) if last else max_back
    return {"style": entry["window"], "since": iso(since), "until": iso(now)}


def derive_lists(parsed: ParsedTodo, log: ParsedLog, cfg: dict, today: date) -> dict:
    focus, intake = cfg["focus"], cfg["intake"]
    open_tasks = [t for t in parsed.tasks if is_open(t)]
    nudges = sorted((t for t in open_tasks if parse_date(t["fields"].get("nudge"))
                     and parse_date(t["fields"]["nudge"]) <= today),
                    key=lambda t: (t["fields"]["nudge"], num(t["id"])))
    horizon = today + timedelta(days=focus["due_soon_days"])
    due = []
    for t in open_tasks:
        d = parse_date(t["fields"].get("due"))
        if d and d <= horizon:
            due.append({"id": t["id"], "due": d.isoformat(), "days_left": (d - today).days})
    due.sort(key=lambda x: (x["due"], num(x["id"])))
    stale: list[str] = []
    n = focus["stale_after_days"]
    if len(log.entries) >= n:
        newest = sorted(log.entries, key=lambda e: e["date"], reverse=True)[:n]
        blob = "\n".join(e["text"] for e in newest)
        for t in sorted(open_tasks, key=lambda t: num(t["id"])):
            nd = parse_date(t["fields"].get("nudge"))
            if nd and nd > today:
                continue
            if not mentions(blob, t["id"]):
                stale.append(t["id"])
    expiring = []
    for t in parsed.tasks:
        if t["section"] == "Proposed":
            p = parse_date(t["fields"].get("proposed"))
            if p and p + timedelta(days=intake["proposal_ttl_days"]) <= today:
                expiring.append(t["id"])
    return {"nudges_due": [t["id"] for t in nudges], "due_soon": due,
            "stale_tasks": stale, "expiring_proposals": sorted(expiring, key=num)}


def collector_input(parsed: ParsedTodo, log: ParsedLog) -> dict:
    """The three blocks every collector prompt needs, so nobody assembles them by hand."""
    known = []
    for t in parsed.tasks:
        if t["state"] != " ":
            continue
        row = f"{t['id']} | {t['title']}"
        if t["fields"].get("waiting"):
            row += f" | waiting: {t['fields']['waiting']}"
        if t["fields"].get("src"):
            row += f" | src: {t['fields']['src']}"
        if t["section"] in ("Proposed", "Parked"):
            row += f" | ({t['section'].lower()})"
        known.append(row)
    for u in parsed.unparsed:
        if u["section"] in TASK_SECTIONS and not u["text"].lstrip().startswith("#"):
            known.append(f"(typed by the user, no id yet) | {u['text'].strip()}")
    closed = [f"{e['date'].isoformat()} {b['verb']}: {b['text']}"
              for e in log.entries if e["date"] is not None
              for b in e["bullets"] if b["verb"] in ("done", "dropped")]
    return {"known_tasks": known, "closed": closed,
            "dismissed": [d["ref"] for d in parsed.dismissed]}


def calendar_table(today: date) -> list[str]:
    """Dates with weekdays around today, for resolving 'by Friday' without arithmetic."""
    return [f"{d.isoformat()} {weekday(d)}"
            for d in (today + timedelta(days=k) for k in range(-7, 15))]


def effective_next_id(state: dict, todo_text: str) -> dict:
    _, max_t, max_g = scan_ids(todo_text)
    return {"T": max(state["next_id"]["T"], max_t + 1),
            "G": max(state["next_id"]["G"], max_g + 1)}


def cmd_begin(args) -> int:
    ws = require_workspace(args)
    cfg, warnings = load_config(ws)
    zone = Zone(cfg["run"]["timezone"])
    now = get_now(zone)
    today = now.date()
    mode = "interactive" if args.interactive else "daily"
    state, state_warn = load_state(ws)
    warnings += state_warn

    previous_incomplete = False
    lock = read_lock(ws)
    if lock is not None:
        if not lock_is_stale(ws, lock, cfg, now, zone):
            raise TodoError(
                f"another run holds the lock: {describe_lock(lock, now, zone)}. Stop; do not "
                f"force it. If you are certain nothing is running, `todo.py abort` releases "
                f"it.", EXIT_LOCKED)
        previous_incomplete = True
        warnings.append(f"a stale lock from {describe_lock(lock, now, zone)} was removed; "
                        f"that run never reached `finish`")
        try:
            ws.lock.unlink()
        except OSError:
            pass

    for name in ("TODO.md", "log.md", "context.md"):
        p = ws.home / name
        if not p.is_file():
            write_atomic(p, template_text(name))
            warnings.append(f"{name} was missing and was recreated from the template")

    todo_text = read_text(ws.todo) or ""
    log_text = read_text(ws.log) or ""
    parsed = parse_todo(todo_text)
    log = parse_log(log_text)
    resolved, sub_warn = resolve_subskills(ws, cfg)
    warnings += sub_warn

    for d in (ws.state_dir, ws.briefs, ws.archive):
        d.mkdir(parents=True, exist_ok=True)
    backup = make_backup(ws, now)
    lock_data = {"mode": mode, "started": iso(now), "run_date": today.isoformat(),
                 "backup_dir": str(backup), "subskills": [s["name"] for s in resolved]}
    try:
        fd = os.open(ws.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        shutil.rmtree(backup, ignore_errors=True)
        raise TodoError("another run took the lock a moment ago. Stop; do not force it.",
                        EXIT_LOCKED)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(lock_data, indent=2) + "\n")

    try:
        ctx = build_context(ws, cfg, state, zone, now, mode, parsed, log, todo_text,
                            resolved, previous_incomplete, warnings)
    except BaseException:
        try:
            ws.lock.unlink()
        except OSError:
            pass
        raise
    ctx["paths"]["backup"] = str(backup)
    emit(ctx)
    return EXIT_OK


def build_context(ws, cfg, state, zone, now, mode, parsed, log, todo_text, resolved,
                  previous_incomplete, warnings) -> dict:
    today = now.date()
    last = state["last_run"] if isinstance(state.get("last_run"), dict) else None
    last_out = None
    last_date = parse_date(last.get("date")) if last else None
    if last and last_date:
        last_out = {"date": last_date.isoformat(), "weekday": weekday(last_date),
                    "status": last.get("status", "unknown"),
                    "days_ago": (today - last_date).days}
    prev = newest_brief_before(ws, today)
    subs = []
    allow = cfg["automation"]["allow_actions"]
    for s in resolved:
        e = s["entry"]
        src = state["sources"].get(s["name"], {})
        subs.append({
            "name": s["name"], "dir": str(s["dir"]), "skill_file": str(s["skill_file"]),
            "origin": s["origin"],
            "window": window_for(e, src, cfg, now, zone),
            "max_items": e["max_items"], "params": e["params"],
            "allowed_actions": [a.split(".", 1)[1] for a in allow
                                if a.split(".", 1)[0] == s["name"]],
            "last_status": src.get("last_status"),
            "consecutive_failures": int(src.get("consecutive_failures", 0) or 0),
        })
    snapshot = read_text(ws.snapshot)
    edits = {"changed": False, "diff": "", "truncated": False}
    if snapshot is not None and snapshot != todo_text:
        diff = list(difflib.unified_diff(split_lines(snapshot), split_lines(todo_text),
                                         "snapshot", "TODO.md", n=1, lineterm=""))
        edits = {"changed": True, "diff": "\n".join(diff[:200]), "truncated": len(diff) > 200}
    lists = derive_lists(parsed, log, cfg, today)
    return {
        "mode": mode, "home": str(ws.home), "skill_dir": str(SKILL_DIR),
        "now": iso(now), "today": today.isoformat(), "weekday": weekday(today),
        "timezone": zone.display(),
        "first_run": last_out is None,
        "rerun_today": last_out is not None and last_out["date"] == today.isoformat(),
        "previous_run_incomplete": previous_incomplete,
        "last_run": last_out,
        "paths": {
            "config": str(ws.config), "todo": str(ws.todo), "log": str(ws.log),
            "context": str(ws.context), "brief": str(ws.brief(today.isoformat())),
            "previous_brief": str(prev) if prev else None,
            "drafts_dir": str(ws.drafts / today.isoformat()), "backup": None,
        },
        "next_id": effective_next_id(state, todo_text),
        "settings": {k: cfg[k] for k in ("intake", "focus", "automation", "history")},
        "subskills": subs,
        "user_edits": edits,
        "unprocessed": [{"id": t["id"], "state": "done" if t["state"] == "x" else "dropped",
                         "line": t["line"]}
                        for t in parsed.tasks if t["state"] in ("x", "-")],
        "unparsed_lines": parsed.unparsed,
        **lists,
        "collector_input": collector_input(parsed, log),
        "calendar": calendar_table(today),
        "warnings": warnings,
    }


def cmd_lint(args) -> int:
    ws = workspace_for(args)
    if not ws.home.is_dir():
        raise TodoError(f"no workspace at {ws.home}. Run `todo.py init` first.")
    warnings: list[str] = []
    if ws.config.is_file():
        cfg, warnings = load_config(ws)
    else:
        cfg = load_default_config()
    zone = Zone(cfg["run"]["timezone"])
    today = get_now(zone).date().isoformat()
    state, _ = load_state(ws)
    lock = read_lock(ws)
    if lock is not None and lock.get("corrupt"):
        lock = None
    issues, _, _ = collect_issues(ws, cfg, state, lock, today)
    order = {"TODO.md": 0, "log.md": 1, "context.md": 3, "finish": 4}
    issues.sort(key=lambda i: (order.get(i.file, 2), i.line))
    errors = [i for i in issues if i.is_error]
    if args.json:
        emit({"ok": not errors, "errors": [i.as_dict() for i in errors],
              "warnings": [i.as_dict() for i in issues if not i.is_error],
              "run_in_progress": lock is not None})
    else:
        for i in issues:
            print(i.text())
        w = len(issues) - len(errors)
        print("lint: clean" if not issues else
              f"lint: {len(errors)} error(s), {w} warning(s)")
    return EXIT_INVALID if errors else EXIT_OK


def load_default_config() -> dict:
    cfg: dict = {"schema": 1, "subskills": []}
    for table, spec in CONFIG_SPEC.items():
        cfg[table] = {k: (list(d) if isinstance(d, list) else d) for k, (_, d) in spec.items()}
    return cfg


def parse_source_args(items: list[str]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for item in items or []:
        name, eq, rest = item.partition("=")
        status, _, note_text = rest.partition(":")
        if not eq or not name:
            raise TodoError(f"--source {item!r}: expected NAME=STATUS or NAME=STATUS:NOTE")
        if status not in SOURCE_STATUSES:
            raise TodoError(f"--source {item!r}: status must be one of "
                            f"{', '.join(SOURCE_STATUSES)}, got {status!r}")
        if name in out:
            raise TodoError(f"--source {name} was given twice")
        out[name] = (status, note_text.strip())
    return out


def fail_json(errors: list[str], message: str) -> int:
    emit({"ok": False, "errors": errors, "message": message})
    print(f"todo.py: finish refused: {len(errors)} problem(s). {message}", file=sys.stderr)
    return EXIT_INVALID


def cmd_finish(args) -> int:
    ws = require_workspace(args)
    cfg, cfg_warnings = load_config(ws)
    zone = Zone(cfg["run"]["timezone"])
    now = get_now(zone)
    mode = "interactive" if args.interactive else "daily"
    lock = read_lock(ws)
    if lock is None:
        raise TodoError("nothing to finish: no run is in progress (there is no lock). "
                        "Start one with `todo.py begin`.")
    if lock.get("corrupt") or not lock.get("run_date") or not lock.get("backup_dir"):
        raise TodoError("the lock file is unreadable; run `todo.py abort --rollback` and "
                        "start again.")
    if lock.get("mode") != mode:
        other = lock.get("mode")
        raise TodoError(f"the lock was taken by a {other} run, not a {mode} one; finish it "
                        f"with `todo.py finish{' --interactive' if other == 'interactive' else ''}`"
                        f" (or release it with `todo.py abort`).")
    sources = parse_source_args(args.source)
    state, state_warn = load_state(ws)
    run_date = lock["run_date"]

    errors: list[str] = []
    warnings: list[str] = list(cfg_warnings) + state_warn
    if mode == "daily":
        expected = lock.get("subskills", [])
        for name in expected:
            if name not in sources:
                errors.append(f"--source {name}=<ok|partial|unavailable|failed> is missing; "
                              f"every subskill in the run context needs a status")
        for name in sources:
            if name not in expected:
                errors.append(f"--source {name}: not a subskill of this run "
                              f"(expected: {', '.join(expected) or 'none'})")
    elif sources:
        warnings.append("--source is ignored for interactive runs")

    issues, todo_text, log = collect_issues(ws, cfg, state, lock, run_date)
    hard = [i for i in issues if i.is_error]
    soft = [i for i in issues if not i.is_error]
    if errors or hard:
        order = {"TODO.md": 0, "log.md": 1, "context.md": 3, "finish": 4}
        hard.sort(key=lambda i: (order.get(i.file, 2), i.line))
        return fail_json(errors + [i.text() for i in hard],
                         "Nothing was changed and the lock is still held. Fix exactly "
                         "what is listed and run finish again.")
    warnings += [i.text() for i in soft]

    summary: dict = {"ok": True, "mode": mode, "run_date": run_date,
                     "brief": str(ws.brief(run_date)) if mode == "daily" else None}
    if mode == "daily":
        todo_text, archived = housekeeping(ws, cfg, lock, run_date, todo_text, log)
        summary["archived"] = archived
    new_ids = effective_next_id(state, todo_text)
    entry = next((e for e in log.entries
                  if e["date"] and e["date"].isoformat() == run_date), None)
    if entry:
        for m in re.finditer(r"(?<![\w])T(\d+)(?![\w])", entry["text"]):
            new_ids["T"] = max(new_ids["T"], int(m.group(1)) + 1)
        for m in re.finditer(r"(?<![\w])G(\d+)(?![\w.])", entry["text"]):
            new_ids["G"] = max(new_ids["G"], int(m.group(1)) + 1)
    state["next_id"] = new_ids
    if mode == "daily":
        statuses = [s for s, _ in sources.values()]
        started = lock.get("started") or iso(now)
        state["last_run"] = {"date": run_date, "started": started, "finished": iso(now),
                             "status": "ok" if all(s == "ok" for s in statuses) else "partial"}
        for name, (status, text) in sources.items():
            prev = state["sources"].get(name, {})
            rec = {"last_success": prev.get("last_success"), "last_attempt": started,
                   "last_status": status, "last_note": text,
                   "consecutive_failures": int(prev.get("consecutive_failures", 0) or 0)}
            if status == "ok":
                rec["last_success"] = started
                rec["consecutive_failures"] = 0
            else:
                rec["consecutive_failures"] += 1
            if rec["last_success"] is None:
                del rec["last_success"]
            state["sources"][name] = rec
    save_state(ws, state)
    write_atomic(ws.snapshot, todo_text)
    try:
        ws.lock.unlink()
    except OSError:
        pass
    summary["next_id"] = new_ids
    summary["warnings"] = warnings
    emit(summary)
    return EXIT_OK


# ------------------------------------------------------------------------ housekeeping

def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    k = 2
    while True:
        cand = path.with_name(f"{path.name}.{k}")
        if not cand.exists():
            return cand
        k += 1


def housekeeping(ws: Workspace, cfg: dict, lock: dict, run_date: str, todo_text: str,
                 log: ParsedLog) -> tuple[str, dict]:
    today = date.fromisoformat(run_date)
    hist = cfg["history"]
    summary: dict = {"dismissed_removed": 0, "log_entries": [], "briefs": [], "drafts": [],
                     "backups_pruned": 0}

    # Dismissed entries past their keep window
    parsed = parse_todo(todo_text)
    keep_days = cfg["intake"]["dismissed_keep_days"]
    drop_lines = {d["line"] for d in parsed.dismissed
                  if d["date"] and (today - d["date"]).days > keep_days}
    if drop_lines:
        kept = [l for i, l in enumerate(parsed.lines, 1) if i not in drop_lines]
        todo_text = "\n".join(kept) + "\n"
        write_atomic(ws.todo, todo_text)
        summary["dismissed_removed"] = len(drop_lines)

    # log.md: keep the newest N entries, append the rest to archive/log-YYYY-MM.md
    log_text = read_text(ws.log) or ""
    plog = parse_log(log_text)
    keep = hist["log_keep_days"]
    if len(plog.entries) > keep:
        extra = plog.entries[keep:]
        lines = plog.lines
        for e in extra:
            month = e["date"].strftime("%Y-%m")
            target = ws.archive / f"log-{month}.md"
            existing = read_text(target)
            chunk = "\n".join(lines[e["line"] - 1:e["end"]]).rstrip("\n")
            if existing is None:
                existing = (f"# Log archive {month}\n"
                            f"<!-- Moved here by todo.py finish. Not read by daily runs. "
                            f"-->\n")
            if not re.search(rf"^## {e['date'].isoformat()} ", existing, re.M):
                existing = existing.rstrip("\n") + "\n\n" + chunk + "\n"
                write_atomic(target, existing)
            summary["log_entries"].append(e["date"].isoformat())
        cut = extra[0]["line"] - 1
        new_log = "\n".join(lines[:cut]).rstrip("\n") + "\n"
        write_atomic(ws.log, new_log)

    # briefs and draft directories: archive together, unless a task still points at drafts
    referenced = set()
    for t in parse_todo(todo_text).tasks:
        d = t["fields"].get("draft")
        if d:
            norm = os.path.normpath(d).replace(os.sep, "/")
            parts = norm.split("/")
            if len(parts) >= 2 and parts[0] == "drafts":
                referenced.add(parts[1])
    brief_days = sorted((m.group(1) for p in ws.briefs.iterdir()
                         if (m := re.match(r"^(\d{4}-\d{2}-\d{2})\.md$", p.name))),
                        reverse=True) if ws.briefs.is_dir() else []
    if len(brief_days) > hist["brief_keep_days"]:
        cutoff = brief_days[hist["brief_keep_days"] - 1]
        for day in brief_days[hist["brief_keep_days"]:]:
            dest_dir = ws.archive / "briefs"
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ws.brief(day)), str(unique_target(dest_dir / f"{day}.md")))
            summary["briefs"].append(day)
        if ws.drafts.is_dir():
            for p in sorted(ws.drafts.iterdir()):
                if p.is_dir() and RE_DATE.match(p.name) and p.name < cutoff \
                        and p.name not in referenced:
                    dest_dir = ws.archive / "drafts"
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(p), str(unique_target(dest_dir / p.name)))
                    summary["drafts"].append(p.name)

    # backups
    keep_n = hist["backup_keep"]
    current = Path(lock.get("backup_dir", "")).name
    backups = list_backups(ws)
    removable = [b for b in backups if b.name != current]
    excess = len(backups) - keep_n
    for b in removable[:max(excess, 0)]:
        shutil.rmtree(b, ignore_errors=True)
        summary["backups_pruned"] += 1
    return todo_text, summary


# ------------------------------------------------------------------ abort and restore

def restore_files(src: Path, ws: Workspace, with_state: bool) -> list[str]:
    restored = []
    for name, dest in (("TODO.md", ws.todo), ("log.md", ws.log)):
        f = src / name
        if f.is_file():
            write_atomic(dest, read_text(f) or "")
            restored.append(name)
    if with_state and (src / "state.json").is_file():
        old_text = read_text(src / "state.json") or "{}"
        try:
            old = json.loads(old_text)
            old = old if isinstance(old, dict) else {}
        except ValueError:
            old = {}
        cur, _ = load_state(ws)
        merged = default_state()
        if isinstance(old.get("last_run"), dict):
            merged["last_run"] = old["last_run"]
        if isinstance(old.get("sources"), dict):
            merged["sources"] = old["sources"]
        # never let the id counter go backwards: ids are not reused
        for k in ("T", "G"):
            v = old.get("next_id", {}).get(k, 1) if isinstance(old.get("next_id"), dict) else 1
            merged["next_id"][k] = max(cur["next_id"][k], v if type(v) is int else 1)
        save_state(ws, merged)
        restored.append("state.json")
        snap = src / "snapshot.TODO.md"
        if snap.is_file():
            write_atomic(ws.snapshot, read_text(snap) or "")
            restored.append("snapshot.TODO.md")
        elif ws.snapshot.exists():
            ws.snapshot.unlink()
    return restored


def cmd_abort(args) -> int:
    ws = require_workspace(args)
    lock = read_lock(ws)
    if lock is None:
        emit({"ok": True, "released": False, "message": "no run is in progress; nothing to do"})
        return EXIT_OK
    restored: list[str] = []
    if args.rollback:
        backup = Path(lock.get("backup_dir", "")) if lock.get("backup_dir") else None
        if backup is None or not backup.is_dir():
            raise TodoError("cannot roll back: the lock names no backup directory that "
                            "exists. The lock is still held; `todo.py abort` (without "
                            "--rollback) releases it, `todo.py restore --list` shows "
                            "backups.")
        restored = restore_files(backup, ws, with_state=False)
    try:
        ws.lock.unlink()
    except OSError:
        pass
    emit({"ok": True, "released": True, "mode": lock.get("mode"), "rolled_back": restored})
    return EXIT_OK


def cmd_restore(args) -> int:
    ws = require_workspace(args)
    backups = list_backups(ws)
    if args.list:
        emit({"backups": [b.name for b in reversed(backups)]})
        return EXIT_OK
    cfg, _ = load_config(ws)
    zone = Zone(cfg["run"]["timezone"])
    now = get_now(zone)
    lock = read_lock(ws)
    if lock is not None and not lock_is_stale(ws, lock, cfg, now, zone):
        raise TodoError(f"cannot restore while {describe_lock(lock, now, zone)} holds the "
                        f"lock. Finish it, or `todo.py abort`.", EXIT_LOCKED)
    if not backups:
        raise TodoError("there are no backups to restore from")
    if args.name:
        match = [b for b in backups if b.name == args.name]
        if not match:
            raise TodoError(f"no backup named {args.name!r}; `todo.py restore --list` shows "
                            f"them")
        target = match[0]
    else:
        target = backups[-1]
    safety = make_backup(ws, now)
    restored = restore_files(target, ws, with_state=True)
    emit({"ok": True, "restored_from": target.name, "restored": restored,
          "previous_state_saved_as": safety.name})
    return EXIT_OK


# ------------------------------------------------------------------------------ status

RE_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)


def frontmatter(text: str) -> dict[str, str]:
    """Tiny reader for the flat frontmatter a SKILL.md uses (no YAML dependency)."""
    m = RE_FRONT.match(text.replace("\r\n", "\n"))
    out: dict[str, str] = {}
    if not m:
        return out
    key, buf, folded = None, [], False
    for raw in m.group(1).split("\n"):
        k = re.match(r"^([A-Za-z_-]+):\s*(.*)$", raw)
        if k and not raw.startswith((" ", "\t")):
            if key:
                out[key] = " ".join(buf).strip()
            key, rest = k.group(1), k.group(2).strip()
            folded = rest in (">", "|", ">-", "|-")
            buf = [] if folded else [rest.strip("\"'")]
        elif key:
            buf.append(raw.strip())
    if key:
        out[key] = " ".join(b for b in buf if b).strip()
    return out


def first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.search(r"(?<=[.!?])\s", text)
    return text[:m.start()] if m else text


def available_subskills(ws: Workspace, cfg: dict) -> list[dict]:
    enabled = {s["name"] for s in cfg["subskills"] if s["enabled"]}
    found: dict[str, dict] = {}
    for base, origin in ((SKILL_DIR / "subskills", "builtin"), (ws.subskills, "workspace")):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            f = d / "SKILL.md"
            if d.name == "_template" or d.name in RESERVED_SUBSKILLS or not f.is_file():
                continue
            desc = first_sentence(frontmatter(read_text(f) or "").get("description", ""))
            found[d.name] = {"name": d.name, "description": desc, "origin": origin,
                             "enabled": d.name in enabled, "dir": str(d)}
    for s in cfg["subskills"]:
        if s["path"] and s["name"] not in found:
            p = _abs(s["path"]) if s["path"].startswith(("/", "~")) \
                else Path(os.path.abspath(ws.home / s["path"]))
            f = p / "SKILL.md" if p.is_dir() else p
            if f.is_file():
                desc = first_sentence(frontmatter(read_text(f) or "").get("description", ""))
                found[s["name"]] = {"name": s["name"], "description": desc, "origin": "path",
                                    "enabled": bool(s["enabled"]), "dir": str(f.parent)}
    return [found[k] for k in sorted(found)]


def cmd_status(args) -> int:
    ws = workspace_for(args)
    initialised = ws.home.is_dir() and ws.config.is_file()
    out: dict = {"home": str(ws.home), "initialised": initialised, "skill_dir": str(SKILL_DIR)}
    if not initialised:
        out["message"] = f"no workspace yet; run `python3 {SKILL_DIR}/scripts/todo.py init`"
        if args.json:
            emit(out)
        else:
            print(f"workspace: {ws.home} (not initialised)\n{out['message']}")
        return EXIT_OK
    cfg, warnings = load_config(ws)
    zone = Zone(cfg["run"]["timezone"])
    now = get_now(zone)
    today = now.date()
    state, state_warn = load_state(ws)
    warnings += state_warn
    warnings += resolve_subskills(ws, cfg)[1]
    last = state["last_run"] if isinstance(state.get("last_run"), dict) else None
    lock = read_lock(ws)
    lock_out = None
    if lock is not None:
        lock_out = {"mode": lock.get("mode"), "started": lock.get("started"),
                    "run_date": lock.get("run_date"),
                    "stale": lock_is_stale(ws, lock, cfg, now, zone)}
    parsed = parse_todo(read_text(ws.todo) or "")
    by_prio = {f"P{i}": 0 for i in range(4)}
    for t in parsed.tasks:
        if is_open(t):
            by_prio[t["priority"][:2]] += 1
    out.update({
        "now": iso(now), "today": today.isoformat(),
        "last_run": last,
        "ran_today": bool(last and last.get("date") == today.isoformat()),
        "lock": lock_out,
        "counts": {"open": sum(by_prio.values()), "open_by_priority": by_prio,
                   "proposed": sum(1 for t in parsed.tasks if t["section"] == "Proposed"),
                   "parked": sum(1 for t in parsed.tasks if t["section"] == "Parked")},
        "sources": state["sources"],
        "subskills": available_subskills(ws, cfg),
        "warnings": warnings,
    })
    if args.json:
        out["runner"] = cfg["runner"]
        emit(out)
        return EXIT_OK
    print(f"workspace: {ws.home}")
    print(f"today: {today.isoformat()} {weekday(today)}")
    print("last run: " + (f"{last.get('date')} ({last.get('status')})" if last else "never")
          + ("; ran today" if out["ran_today"] else "; not yet today"))
    if lock_out:
        print(f"lock: {lock_out['mode']} run since {lock_out['started']}"
              f"{' (stale)' if lock_out['stale'] else ''}")
    c = out["counts"]
    print(f"open tasks: {c['open']} ("
          + ", ".join(f"{k} {v}" for k, v in by_prio.items())
          + f"); proposed {c['proposed']}; parked {c['parked']}")
    for name, s in sorted(state["sources"].items()):
        extra = f", {s.get('consecutive_failures')} failure(s) in a row" \
            if s.get("consecutive_failures") else ""
        print(f"source {name}: {s.get('last_status')}"
              f" (last success {s.get('last_success', 'never')}{extra})")
    print("subskills:")
    for s in out["subskills"]:
        print(f"  {s['name']:<22} {'enabled ' if s['enabled'] else 'disabled'} "
              f"[{s['origin']}] {s['description']}")
    for w in warnings:
        print(f"warning: {w}")
    return EXIT_OK


def cmd_allowed_tools(args) -> int:
    ws = require_workspace(args)
    cfg, _ = load_config(ws)
    rules, warnings = allowed_tools(ws, cfg)
    for w in warnings:
        note(f"warning: {w}")
    for r in rules:
        print(r)
    return EXIT_OK


# ------------------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", metavar="PATH", default=argparse.SUPPRESS,
                        help="workspace directory (default: $TODO_HOME, the pointer file, "
                             "then ~/todo)")
    p = argparse.ArgumentParser(
        prog="todo.py", description="Bookkeeping for the daily TODO skill.",
        epilog="Exit codes: 0 ok, 1 validation errors, 2 usage/config/workspace problem, "
               "3 another run holds the lock.")
    p.add_argument("--home", metavar="PATH", default=None, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    s = sub.add_parser("home", parents=[common], help="print the resolved workspace path")
    s.set_defaults(fn=cmd_home)

    s = sub.add_parser("init", parents=[common],
                       help="create a workspace from the templates (never overwrites)")
    s.add_argument("--set-default", action="store_true",
                   help="remember this workspace in ${XDG_CONFIG_HOME:-~/.config}/todo-skill/home")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("begin", parents=[common],
                       help="take the run lock, back up, print the run context as JSON")
    s.add_argument("--interactive", action="store_true",
                   help="a quick update during the day, not the daily run")
    s.set_defaults(fn=cmd_begin)

    s = sub.add_parser("lint", parents=[common], help="validate TODO.md, log.md, context.md "
                                                      "and today's brief")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_lint)

    s = sub.add_parser("finish", parents=[common],
                       help="validate, rotate history, record the run, release the lock")
    s.add_argument("--interactive", action="store_true")
    s.add_argument("--source", action="append", default=[], metavar="NAME=STATUS[:NOTE]",
                   help="status of a subskill: ok, partial, unavailable or failed "
                        "(repeat once per subskill)")
    s.set_defaults(fn=cmd_finish)

    s = sub.add_parser("abort", parents=[common], help="release the run lock")
    s.add_argument("--rollback", action="store_true",
                   help="first restore TODO.md and log.md from the run's backup")
    s.set_defaults(fn=cmd_abort)

    s = sub.add_parser("restore", parents=[common],
                       help="put back TODO.md and log.md from a backup")
    s.add_argument("--list", action="store_true", help="list backups, newest first")
    s.add_argument("name", nargs="?", help="backup name (default: the newest)")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("status", parents=[common], help="workspace, last run, health")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("allowed-tools", parents=[common],
                       help="permission rules an unattended run needs, one per line")
    s.set_defaults(fn=cmd_allowed_tools)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except TodoError as exc:
        print(f"todo.py: {exc.message}", file=sys.stderr)
        return exc.code
    except BrokenPipeError:
        return EXIT_OK
    except Exception:  # a bug here must not look like a validation result
        traceback.print_exc()
        print("todo.py: internal error (see traceback above)", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
