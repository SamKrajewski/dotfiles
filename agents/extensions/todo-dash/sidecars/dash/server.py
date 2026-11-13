#!/usr/bin/env python3
"""TODO Dash: a Jetski UI sidecar for the daily todo skill's workspace.

Serves a small single-page dashboard over the todo workspace (~/todo by default):
goals with subgoal progress, tasks, proposals, history, briefs, drafts and the documents
tasks point at. Edits (priority, pin, done/drop/park, quick-add) are written straight
into TODO.md exactly as the user would type them, so the skill's next run picks them up
as user edits. Nothing here writes to log.md, briefs, or .state: that is the skill's job.

Parsing is delegated to the skill's own scripts/todo.py so the two never disagree.

Standard library only. Listens on $ANTIGRAVITY_SIDECAR_WEB_PORT (127.0.0.1).
"""

from __future__ import annotations

import argparse
import hmac
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SIDECAR_TOKEN = os.environ.get("ANTIGRAVITY_SIDECAR_TOKEN", "")
AGENTAPI_BIN = os.environ.get("ANTIGRAVITY_AGENTAPI_BIN", "agentapi")
DATA_DIR = Path(os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR")
                or Path.home() / ".gemini" / "jetski" / "sidecar_data" / "todo-dash" / "data")

SKILL_CANDIDATES = [
    os.environ.get("TODO_SKILL_DIR", ""),
    "~/.gemini/config/skills/todo",
    "~/.config/agents/skills/todo",
]

RE_URL = re.compile(r"https?://[^\s)>\]]+")
RE_CONV = re.compile(r"conversation://([0-9a-f-]{36})")
RE_SRC = re.compile(r'^(?P<sub>[\w-]+)\s+"(?P<label>[^"]*)"\s*(?P<date>\d{4}-\d{2}-\d{2})?(?P<rest>.*)$')
RE_LOG_ITEM_ID = re.compile(r"^(T\d+)\b\s*(.*)$")
RE_VALID_CID = re.compile(r"^[0-9a-fA-F-]{8,64}$")

_lock = threading.Lock()


# ----------------------------------------------------------------------------- skill import

def find_skill_dir() -> Path | None:
    for c in SKILL_CANDIDATES:
        if not c:
            continue
        p = Path(os.path.expanduser(c))
        if (p / "scripts" / "todo.py").is_file():
            return p.resolve()
    return None


SKILL_DIR = find_skill_dir()
todo = None
if SKILL_DIR is not None:
    spec = importlib.util.spec_from_file_location("todo_skill", SKILL_DIR / "scripts" / "todo.py")
    todo = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    try:
        spec.loader.exec_module(todo)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        print(f"todo-dash: could not import todo.py: {exc}", file=sys.stderr)
        todo = None


def resolve_home(override: str | None) -> Path:
    if override:
        return Path(os.path.expanduser(override)).resolve()
    if todo is not None:
        try:
            return Path(todo.resolve_home(None)).resolve()
        except Exception:  # noqa: BLE001
            pass
    env = os.environ.get("TODO_HOME")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    pointer = Path(os.path.expanduser("~/.config/todo-skill/home"))
    if pointer.is_file():
        return Path(os.path.expanduser(pointer.read_text().strip())).resolve()
    return (Path.home() / "todo").resolve()


# ----------------------------------------------------------------------------- helpers

def read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write_atomic(p: Path, text: str) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def today_str() -> str:
    return date.today().isoformat()


def parse_src(value: str | None) -> dict:
    if not value:
        return {"kind": "none", "raw": ""}
    if value == "user":
        return {"kind": "user", "raw": value}
    m = RE_SRC.match(value)
    out: dict[str, Any] = {"kind": "source", "raw": value}
    if m:
        out.update({"subskill": m.group("sub"), "label": m.group("label"), "date": m.group("date")})
        rest = m.group("rest") or ""
    else:
        rest = value
    url = RE_URL.search(rest) or RE_URL.search(value)
    conv = RE_CONV.search(value)
    if url:
        out["url"] = url.group(0).rstrip(">.,")
    if conv:
        out["conversation"] = conv.group(1)
    else:
        m_uuid = RE_UUID.search(value)
        if m_uuid:
            out["conversation"] = m_uuid.group(0)
    if not m and url and url.group(0) == value.strip():
        out["kind"] = "url"
    return out


def days_until(d: str | None) -> int | None:
    if not d:
        return None
    try:
        return (date.fromisoformat(d) - date.today()).days
    except ValueError:
        return None


# ----------------------------------------------------------------------------- model

class Dash:
    def __init__(self, home: Path):
        self.home = home
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.index_path = DATA_DIR / f"task_index{'' if home == Path.home() / 'todo' else '-' + re.sub(r'[^A-Za-z0-9]+', '_', str(home))}.json"
        self.index = self._load_index()

    # ---- paths
    @property
    def todo_md(self) -> Path:
        return self.home / "TODO.md"

    @property
    def state_dir(self) -> Path:
        return self.home / ".state"

    def _load_index(self) -> dict:
        raw = read_text(self.index_path)
        if raw:
            try:
                d = json.loads(raw)
                if isinstance(d, dict) and isinstance(d.get("tasks"), dict):
                    return d
            except ValueError:
                pass
        return {"schema": 1, "tasks": {}}

    def _save_index(self) -> None:
        try:
            write_atomic(self.index_path, json.dumps(self.index, indent=1, ensure_ascii=False))
        except OSError as exc:
            print(f"todo-dash: cannot save index: {exc}", file=sys.stderr)

    # ---- run status
    def run_status(self) -> dict:
        lock_path = self.state_dir / "run.lock"
        lock = None
        if lock_path.is_file():
            try:
                lock = json.loads(lock_path.read_text())
            except ValueError:
                lock = {"corrupt": True}
        state = {}
        st = read_text(self.state_dir / "state.json")
        if st:
            try:
                state = json.loads(st)
            except ValueError:
                state = {}
        last_run = state.get("last_run") if isinstance(state, dict) else None
        ran_today = bool(last_run and str(last_run.get("date", "")) == today_str())
        return {
            "locked": lock is not None,
            "lock": lock,
            "last_run": last_run,
            "ran_today": ran_today,
            "sources": state.get("sources", {}) if isinstance(state, dict) else {},
            "next_id": state.get("next_id") if isinstance(state, dict) else None,
        }

    # ---- log
    def parse_logs(self, include_archive: bool = True) -> list[dict]:
        entries: list[dict] = []
        texts = []
        t = read_text(self.home / "log.md")
        if t:
            texts.append(t)
        if include_archive:
            for p in sorted((self.home / "archive").glob("log-*.md"), reverse=True):
                a = read_text(p)
                if a:
                    texts.append(a)
        if todo is None:
            return entries
        seen = set()
        for text in texts:
            parsed = todo.parse_log(text)
            for e in getattr(parsed, "entries", []):
                d = e.get("date")
                key = d.isoformat() if hasattr(d, "isoformat") else str(d)
                if not d or key in seen:
                    continue
                seen.add(key)
                bullets = []
                for b in e.get("bullets", []):
                    verb = b.get("verb")
                    items = []
                    for raw in re.split(r";\s+", b.get("text", "") or ""):
                        raw = raw.strip()
                        if not raw:
                            continue
                        m = RE_LOG_ITEM_ID.match(raw)
                        items.append({"id": m.group(1) if m else None,
                                      "text": m.group(2) if m else raw, "raw": raw})
                    bullets.append({"verb": verb, "items": items, "raw": b.get("text", "")})
                entries.append({"date": key, "weekday": todo.weekday(d), "bullets": bullets})
        entries.sort(key=lambda e: e["date"] or "", reverse=True)
        return entries

    # ---- the full state
    def snapshot(self) -> dict:
        text = read_text(self.todo_md)
        if todo is None:
            return {"error": "todo skill scripts/todo.py not found; set TODO_SKILL_DIR",
                    "home": str(self.home)}
        if text is None:
            return {"error": f"no TODO.md at {self.todo_md}; run `todo.py init`", "home": str(self.home)}
        parsed = todo.parse_todo(text)
        lines = parsed.lines
        logs = self.parse_logs()
        log_closed: dict[str, dict] = {}
        for e in logs:
            for b in e["bullets"]:
                if b["verb"] in ("done", "dropped"):
                    for it in b["items"]:
                        if it["id"] and it["id"] not in log_closed:
                            log_closed[it["id"]] = {"how": b["verb"], "date": e["date"], "title": it["text"]}

        tasks = []
        for t in parsed.tasks:
            f = t["fields"]
            src = parse_src(f.get("src"))
            prio = t["priority"] or ""
            tasks.append({
                "id": t["id"], "title": t["title"], "state": t["state"],
                "priority": prio.rstrip("!?") if prio else None,
                "pinned": prio.endswith("!"), "provisional": prio.endswith("?"),
                "section": t["section"], "goal": t["goal"], "subgoal": t["subgoal"],
                "parent": t["parent"], "line": t["line"],
                "due": f.get("due"), "due_in": days_until(f.get("due")),
                "next": f.get("next"), "waiting": f.get("waiting"), "nudge": f.get("nudge"),
                "draft": f.get("draft"), "note": f.get("note"),
                "proposed": f.get("proposed"), "parked": f.get("parked"),
                "src": src,
                "open": t["state"] == " " and t["section"] in ("Goals", "Other tasks"),
            })

        # Backfill conversation from recent briefs if src didn't include it
        brief_convs: dict[str, str] = {}
        for p in sorted((self.home / "briefs").glob("*.md"), reverse=True)[:5]:
            text_b = read_text(p) or ""
            for m in re.finditer(r"\*\*(T\d+)\*\*.*?conversation://([0-9a-f-]{36})", text_b):
                tid, cid = m.group(1), m.group(2)
                if tid not in brief_convs:
                    brief_convs[tid] = cid

        for t in tasks:
            if not t["src"].get("conversation") and t["id"] in brief_convs:
                t["src"]["conversation"] = brief_convs[t["id"]]

        # --- maintain the task index (history and progress need it)
        now = today_str()
        idx = self.index["tasks"]
        present = {t["id"] for t in tasks}
        changed = False
        for t in tasks:
            rec = idx.get(t["id"])
            if rec is None:
                rec = {"first_seen": now}
                idx[t["id"]] = rec
                changed = True
            upd = {"title": t["title"], "goal": t["goal"], "subgoal": t["subgoal"],
                   "section": t["section"], "priority": t["priority"], "last_seen": now}
            if rec.get("closed"):
                upd["closed"] = None  # it came back (unparked, un-dropped by hand)
            for k, v in upd.items():
                if rec.get(k) != v:
                    rec[k] = v
                    changed = True
        for tid, rec in idx.items():
            if tid in present or rec.get("closed"):
                continue
            lc = log_closed.get(tid)
            rec["closed"] = {"how": lc["how"] if lc else "gone",
                             "date": lc["date"] if lc else rec.get("last_seen") or now}
            changed = True
        if changed:
            self._save_index()

        # --- goals with progress
        done_when: dict[str, str] = {}
        for g in parsed.goals:
            nxt = lines[g["line"]] if g["line"] < len(lines) else ""
            if nxt.startswith("> "):
                done_when[g["id"]] = re.sub(r"^>\s*(Done when:\s*)?", "", nxt).strip()

        def closed_for(goal_id: str, sub_id: str | None = None) -> list[dict]:
            out = []
            for tid, rec in idx.items():
                if not rec.get("closed") or rec.get("goal") != goal_id:
                    continue
                if sub_id is not None and rec.get("subgoal") != sub_id:
                    continue
                out.append({"id": tid, "title": rec.get("title"), **rec["closed"]})
            out.sort(key=lambda r: r.get("date") or "", reverse=True)
            return out

        def progress(open_n: int, closed: list[dict]) -> dict:
            done_n = sum(1 for c in closed if c["how"] == "done")
            total = open_n + done_n
            return {"open": open_n, "done": done_n,
                    "dropped": sum(1 for c in closed if c["how"] != "done"),
                    "percent": int(round(100 * done_n / total)) if total else 0}

        goals = []
        by_goal: dict[str, dict] = {}
        for g in parsed.goals:
            prio = g["priority"] or ""
            node = {
                "id": g["id"], "title": g["title"], "section": g["section"],
                "priority": prio.rstrip("!") if prio else None, "pinned": prio.endswith("!"),
                "due": g["fields"].get("due"), "due_in": days_until(g["fields"].get("due")),
                "line": g["line"], "done_when": done_when.get(g["id"]),
                "subgoals": [], "tasks": [],
            }
            if g["subgoal"]:
                parent = by_goal.get(g["parent"])
                if parent is not None:
                    parent["subgoals"].append(node)
                    node["inherits_priority"] = node["priority"] is None
            else:
                goals.append(node)
                by_goal[g["id"]] = node
        for t in tasks:
            if t["section"] not in ("Goals", "Parked") or not t["goal"]:
                continue
            g = by_goal.get(t["goal"])
            if g is None:
                continue
            target = g
            if t["subgoal"]:
                target = next((s for s in g["subgoals"] if s["id"] == t["subgoal"]), g)
            target["tasks"].append(t)
        for g in goals:
            for s in g["subgoals"]:
                s["closed"] = closed_for(g["id"], s["id"])
                s["progress"] = progress(sum(1 for t in s["tasks"] if t["state"] == " "), s["closed"])
            g["closed"] = closed_for(g["id"])
            g["progress"] = progress(
                sum(1 for t in g["tasks"] if t["state"] == " ")
                + sum(1 for s in g["subgoals"] for t in s["tasks"] if t["state"] == " "),
                g["closed"])

        # --- documents: everything a task, log or brief points at
        docs = self.collect_documents(tasks, logs)

        # --- briefs, drafts, context
        briefs = sorted([p.name[:-3] for p in (self.home / "briefs").glob("*.md")], reverse=True)
        drafts = []
        for p in sorted((self.home / "drafts").glob("*/*.md"), reverse=True):
            head = read_text(p) or ""
            meta = {}
            if head.startswith("---"):
                for ln in head.split("\n")[1:25]:
                    if ln.strip() == "---":
                        break
                    m = re.match(r"^(\w+):\s*(.*)$", ln)
                    if m:
                        meta[m.group(1)] = m.group(2).strip()
            drafts.append({"path": str(p.relative_to(self.home)), "day": p.parent.name,
                           "for": meta.get("for"), "kind": meta.get("kind"), "to": meta.get("to"),
                           "subject": meta.get("subject")})

        history = [{"id": tid, **rec} for tid, rec in idx.items() if rec.get("closed")]
        for tid, lc in log_closed.items():
            if tid not in idx:
                history.append({"id": tid, "title": lc["title"], "goal": None,
                                "closed": {"how": lc["how"], "date": lc["date"]}})
        history.sort(key=lambda r: r["closed"]["date"] or "", reverse=True)

        counts = {
            "open": sum(1 for t in tasks if t["open"]),
            "proposed": sum(1 for t in tasks if t["section"] == "Proposed"),
            "parked": sum(1 for t in tasks if t["section"] == "Parked"),
            "p0": sum(1 for t in tasks if t["open"] and t["priority"] == "P0"),
            "p1": sum(1 for t in tasks if t["open"] and t["priority"] == "P1"),
            "overdue": sum(1 for t in tasks if t["open"] and t["due_in"] is not None and t["due_in"] < 0),
            "waiting": sum(1 for t in tasks if t["open"] and t["waiting"]),
        }

        return {
            "home": str(self.home), "skill": str(SKILL_DIR), "today": now,
            "weekday": date.today().strftime("%a"),
            "run": self.run_status(),
            "counts": counts,
            "goals": goals,
            "other": [t for t in tasks if t["section"] == "Other tasks"],
            "proposed": [t for t in tasks if t["section"] == "Proposed"],
            "parked": [t for t in tasks if t["section"] == "Parked"],
            "dismissed": [{"ref": d["ref"], "date": d["date"].isoformat() if d["date"] else None,
                           "why": d["why"]} for d in parsed.dismissed],
            "issues": [i.as_dict() if hasattr(i, "as_dict") else str(i) for i in parsed.issues],
            "unparsed": parsed.unparsed,
            "log": logs[:60],
            "history": history[:200],
            "documents": docs,
            "briefs": briefs,
            "drafts": drafts,
            "context": read_text(self.home / "context.md") or "",
            "item_context": self.context_map(),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def collect_documents(self, tasks: list[dict], logs: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}

        def add(url: str, title: str, via: str, task: str | None = None, when: str | None = None):
            key = url
            if key in seen:
                if task and task not in seen[key]["tasks"]:
                    seen[key]["tasks"].append(task)
                return
            kind = "conversation" if url.startswith("conversation://") else "link"
            if url.startswith("draft:"):
                kind = "draft"
            host = urllib.parse.urlparse(url).netloc if kind == "link" else "jetski"
            if "docs.google.com" in host:
                kind = "gdoc"
            elif "drive.google.com" in host:
                kind = "drive"
            elif "mail.google.com" in host:
                kind = "gmail"
            elif "calendar.google.com" in host:
                kind = "calendar"
            elif "critique" in host or "cl/" in url:
                kind = "cl"
            seen[key] = {"url": url, "title": title, "kind": kind, "via": via,
                         "tasks": [task] if task else [], "date": when}

        for t in tasks:
            s = t["src"]
            if s.get("url"):
                add(s["url"], s.get("label") or t["title"], s.get("subskill") or "src", t["id"], s.get("date"))
            if s.get("conversation"):
                add(f"conversation://{s['conversation']}", s.get("label") or t["title"], "jetski", t["id"], s.get("date"))
            if t.get("draft"):
                add(f"draft:{t['draft']}", t["draft"].rsplit("/", 1)[-1], "draft", t["id"])
        # recent briefs' links
        for p in sorted((self.home / "briefs").glob("*.md"), reverse=True)[:5]:
            text = read_text(p) or ""
            for m in RE_URL.finditer(text):
                add(m.group(0).rstrip(">.,)"), m.group(0).rstrip(">.,)"), f"brief {p.name[:-3]}", None, p.name[:-3])
            for m in RE_CONV.finditer(text):
                add(f"conversation://{m.group(1)}", "conversation", f"brief {p.name[:-3]}", None, p.name[:-3])
        docs = list(seen.values())
        docs.sort(key=lambda d: (d["date"] or "", d["title"]), reverse=True)
        return docs

    # ---- file access (read-only, inside the workspace)
    def read_file(self, rel: str) -> tuple[int, dict]:
        p = (self.home / rel).resolve()
        if not str(p).startswith(str(self.home) + os.sep) or p.suffix not in (".md", ".toml", ".txt", ".json"):
            return 403, {"error": "outside the workspace or not a text file"}
        text = read_text(p)
        if text is None:
            return 404, {"error": f"not found: {rel}"}
        return 200, {"path": rel, "text": text}

    # ---- edits
    def _guard(self) -> dict | None:
        if (self.state_dir / "run.lock").is_file():
            return {"error": "A todo run is in progress; TODO.md is locked. Try again in a minute."}
        if todo is None:
            return {"error": "todo skill not found"}
        return None

    def _edit(self, fn) -> tuple[int, dict]:
        with _lock:
            g = self._guard()
            if g:
                return 409, g
            text = read_text(self.todo_md)
            if text is None:
                return 404, {"error": "TODO.md missing"}
            parsed = todo.parse_todo(text)
            lines = list(parsed.lines)
            try:
                msg = fn(parsed, lines)
            except ValueError as exc:
                return 400, {"error": str(exc)}
            new_text = "\n".join(lines).rstrip("\n") + "\n"
            if new_text != text:
                write_atomic(self.todo_md, new_text)
            return 200, {"ok": True, "message": msg}

    @staticmethod
    def _find_task(parsed, tid: str) -> dict:
        for t in parsed.tasks:
            if t["id"] == tid:
                return t
        raise ValueError(f"{tid} not found")

    @staticmethod
    def _find_goal(parsed, gid: str) -> dict:
        for g in parsed.goals:
            if g["id"] == gid:
                return g
        raise ValueError(f"{gid} not found")

    @staticmethod
    def _rebuild_task_line(t: dict, box: str, prio: str, fields: dict) -> str:
        order = ["due", "next", "waiting", "nudge", "draft", "note", "src", "proposed", "parked"]
        keys = [k for k in order if k in fields] + [k for k in fields if k not in order]
        parts = [t["id"], prio, t["title"]] + [f"{k}: {fields[k]}" for k in keys]
        return " " * t["indent"] + f"- [{box}] " + " | ".join(parts)

    def set_task(self, tid: str, priority: str | None, pinned: bool | None, state: str | None) -> tuple[int, dict]:
        def fn(parsed, lines):
            t = self._find_task(parsed, tid)
            cur = t["priority"] or "P2"
            base = cur.rstrip("!?")
            suffix = cur[len(base):]
            if priority is not None:
                if priority not in ("P0", "P1", "P2", "P3"):
                    raise ValueError("priority must be P0..P3")
                base = priority
            if pinned is not None and t["section"] != "Proposed":
                suffix = "!" if pinned else ""
            box = t["state"] if state is None else state
            if box not in (" ", "x", "-"):
                raise ValueError("state must be ' ', 'x' or '-'")
            lines[t["line"] - 1] = self._rebuild_task_line(t, box, base + suffix, dict(t["fields"]))
            return f"{tid} → {base + suffix}{'' if box == ' ' else ' [' + box + ']'}"
        return self._edit(fn)

    def set_goal(self, gid: str, priority: str | None, pinned: bool | None) -> tuple[int, dict]:
        def fn(parsed, lines):
            g = self._find_goal(parsed, gid)
            cur = g["priority"] or ""
            base = cur.rstrip("!")
            suffix = cur[len(base):]
            if priority is not None:
                if priority not in ("P0", "P1", "P2", "P3"):
                    raise ValueError("priority must be P0..P3")
                base = priority
            if pinned is not None:
                suffix = "!" if pinned else ""
            head = "#### " if g["subgoal"] else "### "
            parts = [g["id"], g["title"]]
            if base:
                parts.append(base + suffix)
            for k, v in g["fields"].items():
                parts.append(f"{k}: {v}")
            lines[g["line"] - 1] = head + " | ".join(parts)
            return f"{gid} → {base + suffix or 'inherits'}"
        return self._edit(fn)

    def park_task(self, tid: str) -> tuple[int, dict]:
        def fn(parsed, lines):
            t = self._find_task(parsed, tid)
            if t["section"] == "Parked":
                raise ValueError(f"{tid} is already parked")
            if t["indent"]:
                raise ValueError("park the parent task instead of a sub-task")
            fields = dict(t["fields"])
            fields.pop("proposed", None)
            fields["parked"] = today_str()
            prio = (t["priority"] or "P2").rstrip("?")
            new_line = self._rebuild_task_line({**t, "indent": 0}, " ", prio, fields)
            # remove the task and any sub-tasks that follow it
            start = t["line"] - 1
            end = start + 1
            while end < len(lines) and lines[end].startswith("  - ["):
                end += 1
            block = [new_line] + lines[start + 1:end]
            del lines[start:end]
            self._insert_in_section(lines, "Parked", block)
            return f"{tid} parked"
        return self._edit(fn)

    def move_task(self, tid: str, goal: str | None) -> tuple[int, dict]:
        """Accept a proposal or unpark a task: into a goal, or into ## Other tasks."""
        def fn(parsed, lines):
            t = self._find_task(parsed, tid)
            if t["section"] not in ("Proposed", "Parked", "Other tasks", "Goals"):
                raise ValueError(f"{tid} cannot be moved from {t['section']}")
            if t["indent"]:
                raise ValueError("move the parent task instead of a sub-task")
            fields = dict(t["fields"])
            fields.pop("proposed", None)
            fields.pop("parked", None)
            prio = (t["priority"] or "P2").rstrip("?")
            new_line = self._rebuild_task_line({**t, "indent": 0}, " ", prio, fields)
            start = t["line"] - 1
            end = start + 1
            while end < len(lines) and lines[end].startswith("  - ["):
                end += 1
            block = [new_line] + lines[start + 1:end]
            del lines[start:end]
            if goal:
                self._insert_under_goal(parsed, lines, goal, block)
            else:
                self._insert_in_section(lines, "Other tasks", block)
            return f"{tid} moved to {goal or 'Other tasks'}"
        return self._edit(fn)

    def reject_proposal(self, tid: str, why: str) -> tuple[int, dict]:
        def fn(parsed, lines):
            t = self._find_task(parsed, tid)
            if t["section"] != "Proposed":
                raise ValueError(f"{tid} is not a proposal")
            src = t["fields"].get("src", "user")
            del lines[t["line"] - 1]
            why_clean = (why or "rejected in TODO Dash").replace(" | ", " / ").strip()
            self._insert_in_section(lines, "Dismissed", [f"- {src} | dismissed: {today_str()} | why: {why_clean}"])
            return f"{tid} dismissed"
        return self._edit(fn)

    def add_task(self, title: str, priority: str, goal: str | None, due: str | None) -> tuple[int, dict]:
        def fn(parsed, lines):
            clean = " ".join((title or "").split()).replace(" | ", " / ")
            if not clean:
                raise ValueError("title is empty")
            if priority not in ("P0", "P1", "P2", "P3"):
                raise ValueError("priority must be P0..P3")
            if due and todo.parse_date(due) is None:
                raise ValueError("due must be YYYY-MM-DD")
            _, max_t, _ = todo.scan_ids("\n".join(lines))
            tid = f"T{max(max_t, self._max_known_task_id()) + 1}"
            fields = {"src": "user"}
            if due:
                fields = {"due": due, "src": "user"}
            line = f"- [ ] {tid} | {priority} | {clean} | " + " | ".join(f"{k}: {v}" for k, v in fields.items())
            if goal:
                self._insert_under_goal(parsed, lines, goal, [line])
            else:
                self._insert_in_section(lines, "Other tasks", [line])
            return f"{tid} added"
        return self._edit(fn)

    # ---- per-item context (invisible to TODO.md; <home>/context/<ID>.md)
    RE_ITEM_ID = re.compile(r"^(T\d+|G\d+(?:\.\d+)?)$")

    @property
    def context_dir(self) -> Path:
        return self.home / "context"

    def context_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if not self.context_dir.is_dir():
            return out
        for p in self.context_dir.glob("*.md"):
            if self.RE_ITEM_ID.match(p.stem):
                t = read_text(p)
                if t and t.strip():
                    out[p.stem] = t.strip()
        return out

    def set_context(self, item_id: str, text: str) -> tuple[int, dict]:
        if not self.RE_ITEM_ID.match(item_id or ""):
            return 400, {"error": "id must be T<n>, G<n> or G<n>.<m>"}
        p = self.context_dir / f"{item_id}.md"
        text = (text or "").replace("\r", "").strip()
        if not text:
            if p.exists():
                p.unlink()
            return 200, {"ok": True, "message": f"{item_id} context cleared"}
        self.context_dir.mkdir(parents=True, exist_ok=True)
        write_atomic(p, text + "\n")
        return 200, {"ok": True, "message": f"{item_id} context saved"}

    def append_context(self, item_id: str, line: str) -> None:
        if not self.RE_ITEM_ID.match(item_id or ""):
            return
        self.context_dir.mkdir(parents=True, exist_ok=True)
        p = self.context_dir / f"{item_id}.md"
        cur = (read_text(p) or "").rstrip("\n")
        write_atomic(p, (cur + "\n" if cur else "") + line.strip() + "\n")

    def task_title(self, tid: str) -> str | None:
        text = read_text(self.todo_md)
        if text is None or todo is None:
            return None
        for t in todo.parse_todo(text).tasks:
            if t["id"] == tid:
                return t["title"]
        return None

    def describe_item(self, item_id: str) -> str | None:
        """One line a model can act on: the TODO.md line for a task, or the heading for a goal."""
        text = read_text(self.todo_md)
        if text is None or todo is None:
            return None
        parsed = todo.parse_todo(text)
        for t in parsed.tasks:
            if t["id"] == item_id:
                where = t["section"] + (f" · {t['goal']}" if t["goal"] else "") + (f" / {t['subgoal']}" if t["subgoal"] else "")
                return f"{t['raw'].strip()}   [{where}]"
        for g in parsed.goals:
            if g["id"] == item_id:
                line = parsed.lines[g["line"] - 1].strip()
                nxt = parsed.lines[g["line"]] if g["line"] < len(parsed.lines) else ""
                if nxt.startswith("> "):
                    line += "  " + nxt.strip()
                tasks = [t["id"] for t in parsed.tasks if (t["subgoal"] == item_id if g["subgoal"] else t["goal"] == item_id)]
                return f"{line}   [open tasks: {', '.join(tasks) or 'none'}]"
        return None

    RE_BRIEF_REF = re.compile(r"^brief:(\d{4}-\d{2}-\d{2})$")

    def attachment_block(self, ids: list[str]) -> str:
        ctx = self.context_map()
        parts = []
        for item_id in ids:
            b = self.RE_BRIEF_REF.match(item_id)
            if b:
                p = self.home / "briefs" / f"{b.group(1)}.md"
                text = read_text(p)
                if text is None:
                    parts.append(f"- brief:{b.group(1)}: (no such brief)")
                else:
                    parts.append(f"- brief:{b.group(1)}: {p}\n" + "\n".join("    " + l for l in text.strip().splitlines()[:120]))
                continue
            if not self.RE_ITEM_ID.match(item_id):
                continue
            desc = self.describe_item(item_id) or "(not found in TODO.md; it may be closed)"
            block = f"- {item_id}: {desc}"
            if item_id in ctx:
                block += "\n  My notes on it (" + str(self.context_dir / f"{item_id}.md") + "):\n" + "\n".join("    " + l for l in ctx[item_id].splitlines())
            asg = load_assignments().get(item_id)
            if asg and asg.get("conversationId"):
                block += f"\n  Assigned to an agent in conversation://{asg['conversationId']} since {asg.get('started', '')[:10]}"
            parts.append(block)
        if not parts:
            return ""
        return "\n\n[Attached from TODO Dash]\n" + "\n".join(parts)

    # ---- line surgery
    def _max_known_task_id(self) -> int:
        """Highest T id ever seen: file, index, logs, archives and the skill's counter.
        Ids are never reused, so a dismissed or done task still blocks its number."""
        n = 0
        for tid in self.index["tasks"]:
            m = re.match(r"^T(\d+)$", tid)
            if m:
                n = max(n, int(m.group(1)))
        for e in self.parse_logs():
            for b in e["bullets"]:
                for it in b["items"]:
                    if it["id"]:
                        n = max(n, int(it["id"][1:]))
        counter = ((self.run_status().get("next_id") or {}).get("T") or 1) - 1
        for p in [self.todo_md, self.state_dir / "snapshot.TODO.md"]:
            t = read_text(p)
            if t:
                _, max_t, _ = todo.scan_ids(t)
                n = max(n, max_t)
        return max(n, counter)

    @staticmethod
    def _section_bounds(lines: list[str], name: str) -> tuple[int, int]:
        start = next((i for i, l in enumerate(lines) if l.strip() == f"## {name}"), None)
        if start is None:
            raise ValueError(f"section ## {name} missing")
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        return start, end

    def _insert_in_section(self, lines: list[str], name: str, block: list[str]) -> None:
        start, end = self._section_bounds(lines, name)
        # insert before trailing blank lines of the section
        pos = end
        while pos > start + 1 and not lines[pos - 1].strip():
            pos -= 1
        if pos == start + 1 and lines[start + 1:pos] == [] and (pos >= len(lines) or lines[pos].strip()):
            # section header directly followed by the next section: keep a blank line after the header
            lines[pos:pos] = [""] + block
            if pos + 1 + len(block) < len(lines) and lines[pos + 1 + len(block)].startswith("## "):
                lines.insert(pos + 1 + len(block), "")
            return
        lines[pos:pos] = block

    def _insert_under_goal(self, parsed, lines: list[str], goal_id: str, block: list[str]) -> None:
        g = self._find_goal(parsed, goal_id)
        # the goal's block runs until the next ### / #### / ## heading
        i = g["line"]  # index of the line after the heading (0-based == heading line number)
        end = i
        while end < len(lines) and not re.match(r"^(##|###|####) ", lines[end]):
            end += 1
        pos = end
        while pos > i and not lines[pos - 1].strip():
            pos -= 1
        lines[pos:pos] = block


# ----------------------------------------------------------------------------- agentapi

def run_agentapi(args: list[str], project_id: str | None = None) -> dict:
    env = os.environ.copy()
    if project_id:
        env["ANTIGRAVITY_PROJECT_ID"] = project_id
    res = subprocess.run([AGENTAPI_BIN] + args, capture_output=True, text=True, env=env, timeout=30, check=False)
    if res.returncode != 0 and "cross-project" in (res.stderr or "") and "ANTIGRAVITY_SOURCE_METADATA" in env:
        env.pop("ANTIGRAVITY_SOURCE_METADATA", None)
        res = subprocess.run([AGENTAPI_BIN] + args, capture_output=True, text=True, env=env, timeout=30, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"agentapi failed: {res.stderr.strip()[-300:]}")
    out = res.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except ValueError:
        return {"raw": out}


# ----------------------------------------------------------------------------- chat (a dedicated TODO conversation)

BRAIN_DIR = Path(os.path.expanduser(os.environ.get("JETSKI_BRAIN") or "~/.gemini/jetski/brain"))
RE_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RE_USER_REQ = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.S)
RE_DROP = re.compile(r"<(ADDITIONAL_METADATA|SYSTEM_MESSAGE)[^>]*>.*?</\1>", re.S)
CHAT_MARK = "\n\n---\nMessage:\n"


def chat_framing(skill: Path | None, home: Path) -> str:
    return (
        "You are my TODO assistant, talking to me from the TODO Dash side panel. For everything in this "
        f"conversation use the todo skill: read {skill}/SKILL.md first. The workspace is {home}. "
        f"Call the bookkeeping script only by its absolute path, python3 {skill}/scripts/todo.py, never with cd. "
        "Typical requests: quick updates (done/add/drop/park/reprioritise, follow the skill's 'Quick updates' mode), "
        "questions about my goals and tasks, triaging proposals, preparing drafts, or running the daily run when I "
        "explicitly ask. Ask before writing TODO.md when a request is ambiguous; otherwise just do it. "
        "If I ever tell you something is incorrect, you can just remove it: the purpose of this skill is primarily "
        "for you to automatically find tasks and add them, so if one is completely off base, it just needs to be "
        "removed. If I tell you something is partially incorrect, I will usually give you the correction in the "
        "initial message. "
        f"Every goal and task may have a private context file at {home}/context/<ID>.md (for example "
        f"{home}/context/T12.md or {home}/context/G1.md) holding my own notes and amendments about it; it is not part "
        "of TODO.md. Read an item's file before working on that item. When I tell you background about a specific "
        "item that is not a TODO.md field, append it there as a dated line (YYYY-MM-DD: ...) rather than inventing a "
        "field. Messages may end with an '[Attached from TODO Dash]' block: those are the items I am talking about, "
        "with their notes. Keep replies short: the panel shows them in a narrow column. I will keep sending messages "
        "in this same conversation."
    )


def clean_user_text(text: str) -> str:
    m = RE_USER_REQ.findall(text)
    body = "\n".join(m) if m else RE_DROP.sub("", text)
    if CHAT_MARK.strip() in body:
        body = body.split(CHAT_MARK.strip(), 1)[1]
    return body.strip()


def _tool_summary(name: str, args: dict) -> tuple[str, str]:
    """(short label, detail) for a tool call, in the spirit of Jetski's step rows."""
    def s(v) -> str:
        v = "" if v is None else str(v)
        return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v
    a = {k: s(v) for k, v in (args or {}).items()}
    if a.get("toolSummary"):
        return a["toolSummary"], a.get("CommandLine", "")
    if name == "run_command":
        cmd = a.get("CommandLine", "")
        return (cmd[:70] + ("…" if len(cmd) > 70 else "")) or "Run command", cmd
    if name in ("read_file", "write_file", "edit_file"):
        p = a.get("Path", "")
        verb = {"read_file": "Read", "write_file": "Write", "edit_file": "Edit"}[name]
        return f"{verb} {os.path.basename(p) or p}", p
    if name == "invoke_subagent":
        return f"Subagent: {a.get('Role') or a.get('TypeName') or ''}".strip(), (a.get("Prompt") or "")[:300]
    if name in ("search_web", "moma_search", "skill_search"):
        return f"Search: {a.get('query') or a.get('Query') or ''}"[:80], ""
    if name == "ask_question":
        return "Asking you a question", ""
    return name.replace("_", " "), ", ".join(f"{k}={v[:40]}" for k, v in a.items() if k != "toolSummary")[:200]

def read_conversation(cid: str) -> dict:
    logs = BRAIN_DIR / cid / ".system_generated" / "logs"
    p = logs / "transcript_full.jsonl"
    try:
        if not p.is_file() or p.stat().st_size > 8_000_000:
            p = logs / "transcript.jsonl"
    except OSError:
        p = logs / "transcript.jsonl"
    items: list[dict] = []
    working = False
    pending_tools: list[dict] = []
    if p.is_file():
        with p.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    s = json.loads(line)
                except ValueError:
                    continue
                t = s.get("type")
                at = s.get("created_at")
                if t == "USER_INPUT":
                    for tool in pending_tools:
                        tool["status"] = "done"
                    pending_tools = []
                    items.append({"role": "user", "kind": "text", "text": clean_user_text(s.get("content") or ""), "at": at})
                    working = True
                elif t == "PLANNER_RESPONSE":
                    for tool in pending_tools:
                        tool["status"] = "done"
                    pending_tools = []
                    think = (s.get("thinking") or "").strip()
                    if think:
                        items.append({"role": "agent", "kind": "thinking", "text": think[:6000], "at": at})
                    content = (s.get("content") or "").strip()
                    if content:
                        items.append({"role": "agent", "kind": "text", "text": content, "at": at})
                    for tc in s.get("tool_calls") or []:
                        label, detail = _tool_summary(tc.get("name", ""), tc.get("args") or {})
                        tool = {"role": "agent", "kind": "tool", "name": tc.get("name", ""), "label": label,
                                "detail": detail, "status": "running", "result": "", "at": at}
                        items.append(tool)
                        pending_tools.append(tool)
                    if s.get("status") == "ERROR" or s.get("error"):
                        items.append({"role": "agent", "kind": "error", "text": str(s.get("error") or "The agent hit an error."), "at": at})
                        working = False
                    else:
                        working = bool(pending_tools)
                elif t == "GENERIC":
                    out = (s.get("content") or "").strip()
                    if pending_tools:
                        # one result blob per planner step; attach it to its tool(s)
                        pending_tools[0]["result"] = out[:3000] + ("\n…" if len(out) > 3000 else "")
                        for tool in pending_tools:
                            tool["status"] = "error" if s.get("error") else "done"
                        pending_tools = []
                    working = True
    if not working:
        for it in items:
            if it.get("kind") == "tool" and it.get("status") == "running":
                it["status"] = "done"
    return {"conversationId": cid, "items": items[-400:], "working": working, "exists": p.is_file()}


CHANNELS = ("main", "brief")


class Chat:
    """One agent conversation per channel: 'main' (the Chat tab) and 'brief' (the thread
    attached to the daily brief, shared by the Today and Brief pages)."""

    def __init__(self, home: Path, skill: Path | None, channel: str = "main"):
        self.home, self.skill, self.channel = home, skill, channel
        self.path = DATA_DIR / ("chat.json" if channel == "main" else f"chat-{channel}.json")

    def load(self) -> dict:
        raw = read_text(self.path)
        if raw:
            try:
                return json.loads(raw)
            except ValueError:
                pass
        return {}

    def save(self, d: dict) -> None:
        write_atomic(self.path, json.dumps(d, indent=1))

    def transcript(self, cid: str) -> dict:
        return read_conversation(cid)

    def state(self) -> dict:
        d = self.load()
        cid = d.get("conversationId")
        if not cid:
            return {"conversationId": None, "items": [], "working": False, "exists": False}
        out = self.transcript(cid)
        out["started"] = d.get("started")
        return out

    def send(self, text: str, model: str | None = None, attachment: str = "") -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        text = text + (attachment or "")
        d = self.load()
        cid = d.get("conversationId")
        if cid and self.transcript(cid)["exists"]:
            run_agentapi(["send-message", cid, text])
            return {"conversationId": cid, "sent": True}
        framing = chat_framing(self.skill, self.home)
        if self.channel == "brief":
            framing += (" This particular thread is where I discuss my daily briefs: each of my messages arrives "
                        "with the brief I am looking at attached. Answer in the context of that brief (its focus, "
                        "proposals, follow-ups and questions), and when I accept, reject, finish or correct something, "
                        "make the change with a quick update.")
        prompt = framing + CHAT_MARK + text
        args = ["new-conversation", "--title", "TODO Dash" if self.channel == "main" else "TODO Dash: brief"]
        if model:
            args += ["--model", model]
        res = run_agentapi(args + [prompt])
        cid = None
        for k, v in (res.items() if isinstance(res, dict) else []):
            if isinstance(v, str) and RE_UUID.fullmatch(v) and "conv" in k.lower():
                cid = v
        if not cid:
            m = RE_UUID.search(json.dumps(res))
            cid = m.group(0) if m else None
        if not cid:
            raise RuntimeError(f"could not read the conversation id from agentapi: {res}")
        self.save({"conversationId": cid, "started": datetime.now().isoformat(timespec="seconds")})
        return {"conversationId": cid, "sent": True, "new": True}

    def reset(self) -> dict:
        d = self.load()
        old = d.get("conversationId")
        if self.path.exists():
            self.path.unlink()
        return {"reset": True, "previous": old}


# ----------------------------------------------------------------------------- assignments (a task delegated to its own agent conversation)

ASSIGN_FILE_NAME = "assignments.json"


def load_assignments() -> dict:
    raw = read_text(DATA_DIR / ASSIGN_FILE_NAME)
    if raw:
        try:
            d = json.loads(raw)
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
    return {}


def save_assignments(d: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(DATA_DIR / ASSIGN_FILE_NAME, json.dumps(d, indent=1))


def assign_framing(skill: Path | None, home: Path, tid: str) -> str:
    return (
        f"I have assigned you one task from my TODO list through TODO Dash: {tid}. The task line, my private notes on it "
        "and any linked source are attached at the end of this message.\n\n"
        f"Setup: the todo skill is at {skill}/SKILL.md (read it first); the workspace is {home}; call the bookkeeping "
        f"script only by its absolute path, python3 {skill}/scripts/todo.py, never with cd. The task's context file is "
        f"{home}/context/{tid}.md.\n\n"
        "Your job is to get the task done, or as far as it can be taken from this machine without me:\n"
        "1. Say in two or three lines what you understand the task to be and what you will do. If the task is too vague "
        "to act on, ask me one precise question and stop.\n"
        "2. Do the work: code, documents, analysis, lookups, drafts, CL preparation, whatever the task needs. Use the "
        "source linked in the task and my notes.\n"
        "3. Never send, submit, share, post, approve, accept, pay or delete anything that reaches other people or cannot "
        "be undone without asking me first in this conversation: prepare it, show me, and wait.\n"
        "4. When you finish, get blocked, or have a result worth recording, update the todo through the skill's "
        "'Quick updates' mode (todo.py begin --interactive … finish --interactive): set next:, add draft: for anything "
        "you prepared (put files under the workspace's drafts/ directory), set waiting: if it is now on someone else, "
        "or mark the task [x] if it is genuinely done. Then append one dated line (YYYY-MM-DD: …) to the context file "
        "saying what you did and where the output is.\n"
        "5. End with a short report: done / still open / needs me.\n"
        "If I reply here later, continue the work in this same conversation."
    )


class Assignments:
    def __init__(self, dash: Dash, skill: Path | None):
        self.dash, self.skill = dash, skill

    def assign(self, tid: str, instructions: str = "") -> dict:
        if not re.match(r"^T\d+$", tid or ""):
            raise ValueError("only tasks (T<n>) can be assigned")
        title = self.dash.task_title(tid)
        if title is None:
            raise ValueError(f"{tid} is not in TODO.md")
        cur = load_assignments()
        if cur.get(tid, {}).get("conversationId"):
            raise ValueError(f"{tid} is already assigned; unassign it first or nudge the agent")
        prompt = assign_framing(self.skill, self.dash.home, tid)
        instructions = (instructions or "").strip()
        if instructions:
            prompt += f"\n\nExtra instructions from me: {instructions}"
        prompt += self.dash.attachment_block([tid])
        res = run_agentapi(["new-conversation", "--title", f"TODO {tid}: {title[:60]}", prompt])
        m = RE_UUID.search(json.dumps(res))
        if not m:
            raise RuntimeError(f"could not read the conversation id from agentapi: {res}")
        rec = {"conversationId": m.group(0), "started": datetime.now().isoformat(timespec="seconds"),
               "instructions": instructions, "title": title}
        cur[tid] = rec
        save_assignments(cur)
        self.dash.append_context(tid, f"{today_str()}: assigned to an agent (conversation://{rec['conversationId']})"
                                 + (f" — {instructions}" if instructions else ""))
        return {"ok": True, "message": f"{tid} assigned to an agent", **rec}

    def nudge(self, tid: str, text: str) -> dict:
        rec = load_assignments().get(tid)
        if not rec or not rec.get("conversationId"):
            raise ValueError(f"{tid} is not assigned")
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        run_agentapi(["send-message", rec["conversationId"], text])
        return {"ok": True, "message": f"sent to {tid}'s agent"}

    def unassign(self, tid: str) -> dict:
        cur = load_assignments()
        rec = cur.pop(tid, None)
        save_assignments(cur)
        if rec:
            self.dash.append_context(tid, f"{today_str()}: unassigned from the agent (conversation://{rec.get('conversationId', '')})")
        return {"ok": True, "message": f"{tid} unassigned"}

    def status(self) -> dict:
        out = {}
        for tid, rec in load_assignments().items():
            cid = rec.get("conversationId")
            info = {"conversationId": cid, "started": rec.get("started"), "instructions": rec.get("instructions", ""),
                    "working": False, "last_text": "", "last_at": None, "asked": False, "exists": False}
            if cid:
                t = read_conversation(cid)
                info["exists"] = t["exists"]
                info["working"] = t["working"]
                texts = [i for i in t["items"] if i["role"] == "agent" and i["kind"] == "text"]
                if texts:
                    last = texts[-1]
                    info["last_text"] = last["text"][:700]
                    info["last_at"] = last["at"]
                    info["asked"] = (not t["working"]) and last["text"].rstrip().endswith("?")
                info["tools"] = sum(1 for i in t["items"] if i["kind"] == "tool")
            out[tid] = info
        return out


# ----------------------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    dash: Dash = None  # type: ignore[assignment]
    chats: dict = {}
    assignments: Assignments = None  # type: ignore[assignment]

    @classmethod
    def chat_for(cls, channel) -> "Chat":
        channel = channel if channel in CHANNELS else "main"
        return cls.chats[channel]

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("TODO_DASH_DEBUG"):
            super().log_message(fmt, *args)

    def _ok_token(self) -> bool:
        if not SIDECAR_TOKEN:
            return True
        return hmac.compare_digest(self.headers.get("X-Sidecar-Token", ""), SIDECAR_TOKEN)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name: str, ctype: str) -> None:
        p = HERE / name
        if not p.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = p.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        p = u.path
        qs = urllib.parse.parse_qs(u.query)
        if p in ("/", "/index.html"):
            return self._file("index.html", "text/html; charset=utf-8")
        if p == "/styles.css":
            return self._file("styles.css", "text/css; charset=utf-8")
        if p == "/app.js":
            return self._file("app.js", "application/javascript; charset=utf-8")
        if p == "/preload.js":
            return self._file("preload.js", "application/javascript; charset=utf-8")
        if p == "/healthz":
            return self._json(200, {"ok": True})
        if p == "/api/state":
            try:
                st = self.dash.snapshot()
                if "error" not in st:
                    try:
                        st["assignments"] = self.assignments.status()
                    except Exception as exc:  # noqa: BLE001
                        st["assignments"] = {}
                        st["assignments_error"] = str(exc)
                return self._json(200, st)
            except Exception as exc:  # noqa: BLE001
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        if p == "/api/file":
            rel = (qs.get("path") or [""])[0]
            code, payload = self.dash.read_file(rel)
            return self._json(code, payload)
        if p == "/api/chat/state":
            try:
                return self._json(200, self.chat_for((qs.get("channel") or ["main"])[0]).state())
            except Exception as exc:  # noqa: BLE001
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if not self._ok_token():
            return self._json(403, {"error": "invalid sidecar token"})
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
        except ValueError:
            body = {}
        d = self.dash
        try:
            if u.path == "/api/task/set":
                code, out = d.set_task(str(body.get("id")), body.get("priority"), body.get("pinned"), body.get("state"))
            elif u.path == "/api/goal/set":
                code, out = d.set_goal(str(body.get("id")), body.get("priority"), body.get("pinned"))
            elif u.path == "/api/task/park":
                code, out = d.park_task(str(body.get("id")))
            elif u.path in ("/api/task/accept", "/api/task/move"):
                code, out = d.move_task(str(body.get("id")), body.get("goal"))
            elif u.path == "/api/task/reject":
                code, out = d.reject_proposal(str(body.get("id")), str(body.get("why") or ""))
            elif u.path == "/api/task/add":
                code, out = d.add_task(str(body.get("title") or ""), str(body.get("priority") or "P2"),
                                       body.get("goal"), body.get("due"))
            elif u.path == "/api/chat/send":
                ids = [str(x) for x in (body.get("attach") or []) if isinstance(x, str)][:12]
                code, out = 200, self.chat_for(body.get("channel")).send(str(body.get("text") or ""), body.get("model"), d.attachment_block(ids))
            elif u.path == "/api/task/assign":
                code, out = 200, self.assignments.assign(str(body.get("id") or ""), str(body.get("instructions") or ""))
            elif u.path == "/api/task/nudge":
                code, out = 200, self.assignments.nudge(str(body.get("id") or ""), str(body.get("text") or ""))
            elif u.path == "/api/task/unassign":
                code, out = 200, self.assignments.unassign(str(body.get("id") or ""))
            elif u.path == "/api/context/set":
                code, out = d.set_context(str(body.get("id") or ""), str(body.get("text") or ""))
            elif u.path == "/api/chat/reset":
                code, out = 200, self.chat_for(body.get("channel")).reset()
            elif u.path == "/_sidecar/send-message":
                msg = body.get("message")
                cid = body.get("conversationId") or os.environ.get("ANTIGRAVITY_SIDECAR_CONVERSATION_ID")
                if not msg or not cid:
                    raise ValueError("message and conversationId are required")
                code, out = 200, run_agentapi(["send-message", str(cid), str(msg)], body.get("projectId"))
            elif u.path == "/_sidecar/new-conversation":
                msg = body.get("message")
                if not msg:
                    raise ValueError("message is required")
                args = ["new-conversation"]
                if body.get("title"):
                    args += ["--title", str(body["title"])]
                code, out = 200, run_agentapi(args + [str(msg)], body.get("projectId"))
            elif u.path == "/_sidecar/get-conversation-metadata":
                cid = str(body.get("conversationId") or "")
                if not RE_VALID_CID.match(cid):
                    code, out = 200, {"response": {}}
                else:
                    try:
                        code, out = 200, run_agentapi(["get-conversation-metadata", cid])
                    except RuntimeError:
                        code, out = 200, {"response": {}}
            else:
                code, out = 404, {"error": "unknown endpoint"}
        except (ValueError, RuntimeError) as exc:
            code, out = 400, {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            code, out = 500, {"error": f"{type(exc).__name__}: {exc}"}
        self._json(code, out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT", "8765")))
    ap.add_argument("--home", default=None, help="todo workspace (default: the skill's pointer file)")
    ap.add_argument("--dump", action="store_true", help="print the state JSON and exit")
    args = ap.parse_args()
    home = resolve_home(args.home)
    dash = Dash(home)
    if args.dump:
        print(json.dumps(dash.snapshot(), indent=1, ensure_ascii=False, default=str))
        return
    Handler.dash = dash
    Handler.chats = {ch: Chat(home, SKILL_DIR, ch) for ch in CHANNELS}
    Handler.assignments = Assignments(dash, SKILL_DIR)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"todo-dash: home={home} skill={SKILL_DIR} port={args.port}", file=sys.stderr, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
