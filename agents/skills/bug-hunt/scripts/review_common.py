"""Shared helpers for the bug-hunt skill scripts.

Standard library only, so the scripts run wherever python3 does. PyYAML is
used when present; otherwise a small parser covers the YAML subset used by the
files this skill writes (block maps, block lists, flow maps/lists, scalars).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
REFERENCES_DIR = SKILL_DIR / "references"
SUBSKILLS_DIR = SKILL_DIR / "subskills"

FAMILIES = ("claude", "gpt", "gemini", "other", "human", "unknown")
SEVERITIES = ("critical", "high", "medium")
CONFIDENCES = ("confirmed", "traced", "suspected")
DEPTHS = ("light", "standard", "deep")
PROJECT_KINDS = ("script", "application", "production")

DEFAULT_CONFIG: dict[str, Any] = {
    "default_branch": "",
    "project": {"kind": "application"},
    "limits": {
        "max_findings": 8,
        "max_context_files": 25,
        "budget_usd": {"light": 0.5, "standard": 3, "deep": 10},
    },
    "depth": {
        "skip_globs": [".review/**", "**/*.lock", "dist/**", "vendor/**"],
        "deep_paths": ["**/auth/**", "**/billing/**", "**/migrations/**"],
        "light_max_lines": 20,
        "light_max_files": 2,
        "deep_min_lines": 800,
        "deep_min_files": 30,
    },
    "models": {"small": "", "frontier": "", "computer_use": ""},
    "inversion": {
        "self_family": "",
        "author_override": "",
        "registry": "",
        "reviewers": {"claude": "", "gpt": "", "gemini": ""},
    },
    "context": {"tickets": "none", "docs": ["docs/", "adr/"], "related_repos": []},
    "testing": {"setup": "", "test": "", "start": "", "health_url": ""},
    "evals": {
        "command": "",
        "repeats": 3,
        "line_tolerance": 3,
        "timeout_seconds": 1800,
        "checkout": "auto",
    },
}


# --------------------------------------------------------------------------
# Process and filesystem helpers
# --------------------------------------------------------------------------


def run(cmd: list[str], cwd: pathlib.Path | None = None, check: bool = True,
        timeout: int = 120, input_text: str | None = None) -> str:
    """Runs a command and returns stdout. Raises CalledProcessError if check."""
    proc = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        timeout=timeout, input=input_text, check=False)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)
    return proc.stdout


def try_run(cmd: list[str], cwd: pathlib.Path | None = None,
            timeout: int = 120) -> str | None:
    """Like run(), but returns None when the command fails or is missing."""
    try:
        return run(cmd, cwd=cwd, timeout=timeout)
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired):
        return None


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def read_text(path: pathlib.Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n",
                    encoding="utf-8")


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_name(name: str) -> str:
    """Turns a branch or change name into a filesystem-safe token."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "unnamed"


# --------------------------------------------------------------------------
# Repository discovery and the .review/ directory
# --------------------------------------------------------------------------


def find_repo_root(start: pathlib.Path | None = None) -> tuple[pathlib.Path, str | None]:
    """Returns (root, vcs) where vcs is 'git', 'jj' or None."""
    start = start or pathlib.Path.cwd()
    out = try_run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    if out and out.strip():
        return pathlib.Path(out.strip()).resolve(), "git"
    out = try_run(["jj", "root"], cwd=start)
    if out and out.strip():
        return pathlib.Path(out.strip()).resolve(), "jj"
    return start.resolve(), None


def is_citc_path(path: pathlib.Path) -> bool:
    text = str(path)
    return text.startswith("/google/src/cloud/") or "/.citc/" in text


def review_dir(root: pathlib.Path, override: str | None = None) -> pathlib.Path:
    """Resolves the per-repo state directory.

    Order: explicit override, $CODE_REVIEW_DIR, <root>/.review. CitC
    workspaces are world-readable and keep every write in snapshots, so a
    state directory inside one is refused unless the caller opts in.
    """
    chosen = override or os.environ.get("BUG_HUNT_DIR") or os.environ.get("CODE_REVIEW_DIR")
    if chosen:
        return pathlib.Path(chosen).expanduser().resolve()
    candidate = root / ".review"
    if is_citc_path(candidate) and os.environ.get("CODE_REVIEW_ALLOW_CITC") != "1":
        raise SystemExit(
            "refusing to create .review/ inside a CitC workspace (world-readable, "
            "snapshotted). Set CODE_REVIEW_DIR to a local path, for example:\n"
            "  export CODE_REVIEW_DIR=~/.cache/bug-hunt/" + safe_name(root.name))
    return candidate


def ensure_review_dir(rd: pathlib.Path) -> list[str]:
    """Creates the missing parts of the .review/ skeleton from templates.

    Returns the created paths; the caller can tell a true first run from a
    partially present directory by whether config.yaml is among them.
    """
    created: list[str] = []

    def put(rel: str, content: str) -> None:
        target = rd / rel
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(str(target))

    for sub in ("kb", "evals/cases", "evals/reports", "state", "tmp"):
        path = rd / sub
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))
    put("config.yaml", read_text(TEMPLATES_DIR / "config.yaml"))
    put("flows.yaml", read_text(TEMPLATES_DIR / "flows.yaml"))
    put("kb/INDEX.md", read_text(TEMPLATES_DIR / "kb-index.md"))
    put("bug-catalog.local.md", read_text(TEMPLATES_DIR / "bug-catalog.local.md"))
    put(".gitignore", "# Generated by the bug-hunt skill.\nstate/\ntmp/\n")
    return created


def load_config(rd: pathlib.Path) -> dict[str, Any]:
    """Loads .review/config.yaml merged over DEFAULT_CONFIG."""
    data = parse_yaml(read_text(rd / "config.yaml")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"{rd / 'config.yaml'}: top level must be a mapping")
    return deep_merge(DEFAULT_CONFIG, data)


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {k: v for k, v in base.items()}
        for key, value in override.items():
            merged[key] = deep_merge(base.get(key), value) if key in base else value
        return merged
    return override if override is not None else base


# --------------------------------------------------------------------------
# Globs
# --------------------------------------------------------------------------


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Converts a gitignore-style glob to a regex. '**' crosses directories."""
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def glob_match(path: str, patterns: list[str]) -> str | None:
    """Returns the first pattern matching path, else None."""
    for pattern in patterns or []:
        if glob_to_regex(pattern).match(path):
            return pattern
    return None


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def normalise_code(snippet: str) -> str:
    return re.sub(r"\s+", "", snippet or "")


def finding_id(klass: str, file: str, code: str) -> str:
    """Stable finding ID: class + file + whitespace-free snippet. Line
    numbers are deliberately excluded so that shifts do not change the ID."""
    digest = hashlib.sha256(
        f"{klass.strip()}\n{file.strip()}\n{normalise_code(code)}".encode("utf-8"))
    return digest.hexdigest()[:12]


# --------------------------------------------------------------------------
# YAML (PyYAML when available, otherwise a small subset parser)
# --------------------------------------------------------------------------


def parse_yaml(text: str) -> Any:
    if not text.strip():
        return {}
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        return _MiniYaml(text).parse()


def dump_yaml(data: Any) -> str:
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    except ImportError:
        return _dump_mini(data, 0)


def _dump_mini(data: Any, indent: int) -> str:
    pad = " " * indent
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                lines.append(_dump_mini(value, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_scalar_out(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, dict):
                body = _dump_mini(item, indent + 2).splitlines()
                first = body[0].lstrip() if body else ""
                lines.append(f"{pad}- {first}")
                lines.extend(body[1:])
            else:
                lines.append(f"{pad}- {_scalar_out(item)}")
        return "\n".join(lines)
    return pad + _scalar_out(data)


def _scalar_out(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)) and not value:
        return "{}" if isinstance(value, dict) else "[]"
    text = str(value)
    if text == "" or re.search(r"[:#\[\]{},\"']|^\s|\s$", text) or text.lower() in (
            "true", "false", "null", "yes", "no", "~"):
        return json.dumps(text)
    return text


class _MiniYaml:
    """Parses the YAML subset this skill writes. Not a general YAML parser."""

    def __init__(self, text: str):
        self.lines = self._prepare(text)
        self.pos = 0

    @staticmethod
    def _strip_comment(line: str) -> str:
        out = []
        quote = None
        for i, ch in enumerate(line):
            if quote:
                out.append(ch)
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
                out.append(ch)
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                break
            else:
                out.append(ch)
        return "".join(out).rstrip()

    def _prepare(self, text: str) -> list[tuple[int, str]]:
        prepared = []
        for raw in text.splitlines():
            if raw.strip() in ("---", "..."):
                continue
            line = self._strip_comment(raw.replace("\t", "  "))
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            prepared.append((indent, line.strip()))
        return prepared

    def parse(self) -> Any:
        if not self.lines:
            return {}
        value = self._block(self.lines[0][0])
        if self.pos != len(self.lines):
            indent, text = self.lines[self.pos]
            raise SystemExit(f"yaml: unexpected line {text!r}")
        return value

    def _block(self, indent: int) -> Any:
        _, first = self.lines[self.pos]
        if first.startswith("- ") or first == "-":
            return self._sequence(indent)
        return self._mapping(indent)

    def _sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while self.pos < len(self.lines):
            cur_indent, text = self.lines[self.pos]
            if cur_indent < indent or not (text.startswith("- ") or text == "-"):
                break
            if cur_indent > indent:
                raise SystemExit(f"yaml: bad indentation at {text!r}")
            rest = text[1:].strip()
            self.pos += 1
            if not rest:
                items.append(self._block(self._next_indent(indent)))
            elif self._is_map_entry(rest):
                # Inline mapping start: "- key: value" then deeper keys.
                virtual_indent = cur_indent + 2
                self.lines.insert(self.pos, (virtual_indent, rest))
                items.append(self._mapping(virtual_indent))
            else:
                items.append(self._scalar(rest))
        return items

    def _mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.pos < len(self.lines):
            cur_indent, text = self.lines[self.pos]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise SystemExit(f"yaml: bad indentation at {text!r}")
            if text.startswith("- "):
                break
            key, rest = self._split_entry(text)
            self.pos += 1
            if rest == "":
                if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                    result[key] = self._block(self.lines[self.pos][0])
                elif (self.pos < len(self.lines) and self.lines[self.pos][0] == indent
                      and self.lines[self.pos][1].startswith("- ")):
                    result[key] = self._sequence(indent)
                else:
                    result[key] = None
            else:
                result[key] = self._scalar(rest)
        return result

    def _next_indent(self, indent: int) -> int:
        if self.pos >= len(self.lines) or self.lines[self.pos][0] <= indent:
            raise SystemExit("yaml: expected nested block")
        return self.lines[self.pos][0]

    @staticmethod
    def _is_map_entry(text: str) -> bool:
        if text[0] in "\"'[{":
            return False
        return re.match(r"^[^:]+:(\s|$)", text) is not None

    @staticmethod
    def _split_entry(text: str) -> tuple[str, str]:
        match = re.match(r"^(\"[^\"]*\"|'[^']*'|[^:]+?):(?:\s+(.*))?$", text)
        if not match:
            raise SystemExit(f"yaml: expected 'key: value' but got {text!r}")
        key = match.group(1).strip().strip("\"'")
        return key, (match.group(2) or "").strip()

    def _scalar(self, text: str) -> Any:
        value, rest = self._parse_value(text)
        if rest.strip():
            raise SystemExit(f"yaml: trailing text {rest!r} after {text!r}")
        return value

    def _parse_value(self, text: str) -> tuple[Any, str]:
        text = text.lstrip()
        if not text:
            return None, ""
        if text[0] == "{":
            return self._parse_flow_map(text[1:])
        if text[0] == "[":
            return self._parse_flow_list(text[1:])
        if text[0] in "\"'":
            quote = text[0]
            end = 1
            while end < len(text):
                if text[end] == "\\" and quote == '"':
                    end += 2
                    continue
                if text[end] == quote:
                    break
                end += 1
            body = text[1:end]
            rest = text[end + 1:]
            if quote == '"':
                body = bytes(body, "utf-8").decode("unicode_escape")
            return body, rest
        match = re.match(r"^([^,\]\}]*)", text)
        raw = match.group(1).strip()
        return self._plain(raw), text[len(match.group(1)):]

    def _parse_flow_map(self, text: str) -> tuple[dict[str, Any], str]:
        result: dict[str, Any] = {}
        text = text.lstrip()
        while True:
            if not text:
                raise SystemExit("yaml: unterminated flow mapping")
            if text[0] == "}":
                return result, text[1:]
            match = re.match(r"^\s*(\"[^\"]*\"|'[^']*'|[^:,}]+)\s*:\s*", text)
            if not match:
                raise SystemExit(f"yaml: bad flow mapping near {text[:30]!r}")
            key = match.group(1).strip().strip("\"'")
            value, text = self._parse_value(text[match.end():])
            result[key] = value
            text = text.lstrip()
            if text.startswith(","):
                text = text[1:].lstrip()

    def _parse_flow_list(self, text: str) -> tuple[list[Any], str]:
        result: list[Any] = []
        text = text.lstrip()
        while True:
            if not text:
                raise SystemExit("yaml: unterminated flow list")
            if text[0] == "]":
                return result, text[1:]
            value, text = self._parse_value(text)
            result.append(value)
            text = text.lstrip()
            if text.startswith(","):
                text = text[1:].lstrip()

    @staticmethod
    def _plain(raw: str) -> Any:
        if raw == "" or raw in ("null", "~", "Null", "NULL"):
            return None
        if raw in ("true", "True", "TRUE"):
            return True
        if raw in ("false", "False", "FALSE"):
            return False
        if re.match(r"^-?\d+$", raw):
            return int(raw)
        if re.match(r"^-?\d+\.\d*$", raw) or re.match(r"^-?\.\d+$", raw):
            return float(raw)
        return raw
