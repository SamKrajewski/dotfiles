#!/usr/bin/env python3
"""Unattended daily run, and installing it on a scheduler, for the daily TODO skill.

    schedule.py run [--dry-run] [--force] [--home PATH]
    schedule.py install [--time HH:MM] [--weekdays] [--dry-run] [--home PATH]
                        [--scheduler auto|systemd|launchd|cron]
    schedule.py uninstall [--dry-run] [--home PATH]
    schedule.py show [--home PATH]

`run` starts the agent with an explicit tool allowlist built from config.toml. It never
passes a permission bypass: this agent reads mail and documents written by other people
while nobody is watching. Standard library only; reuses scripts/todo.py.

Exit codes: 0 ok, 1 the run failed, 2 usage/config problem, 3 another run holds the lock.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True   # keep the (possibly read-only) skill directory clean
sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo  # noqa: E402  (same directory)

SERVICE_NAME = "todo-daily.service"
TIMER_NAME = "todo-daily.timer"
LAUNCHD_LABEL = "com.todo-skill.daily"
BASE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Agent", "Task"]
RUNS_LOG_MAX_BYTES = 1_000_000
RE_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# ------------------------------------------------------------------------------ helpers

def note(msg: str) -> None:
    print(f"schedule.py: {msg}", file=sys.stderr)


def load(args) -> tuple[todo.Workspace, dict, list[str]]:
    ws = todo.require_workspace(args)
    cfg, warnings = todo.load_config(ws)
    return ws, cfg, warnings


def build_prompt(skill: Path, home: Path) -> str:
    return (
        "This is an unattended daily TODO run. Nobody is available to answer questions. "
        f"Read {skill}/SKILL.md and carry out the daily run for the workspace at {home}. "
        f"Call the bookkeeping script exactly as `python3 {skill}/scripts/todo.py <command>` "
        "(absolute path, no `cd`), because only that form is permitted. "
        "Your final message must be the brief."
    )


def build_command(ws: todo.Workspace, cfg: dict) -> tuple[list[str], list[str]]:
    """The agent command line, and warnings from resolving the subskills' tools."""
    skill = todo.SKILL_DIR
    runner = cfg["runner"]
    tools, warnings = todo.allowed_tools(ws, cfg)
    allow = BASE_TOOLS + [f"Bash(python3 {skill}/scripts/todo.py *)"] + tools
    cmd = [runner["agent"], "-p", build_prompt(skill, ws.home),
           "--add-dir", str(skill),
           "--permission-mode", "acceptEdits"]
    if runner["model"]:
        cmd += ["--model", runner["model"]]
    if runner["max_budget_usd"]:
        cmd += ["--max-budget-usd", f"{runner['max_budget_usd']:g}"]
    cmd += ["--allowedTools", *dict.fromkeys(allow)]    # variadic, so it goes last
    return cmd, warnings


def run_env(ws: todo.Workspace) -> dict:
    env = dict(os.environ)
    env["TODO_HOME"] = str(ws.home)
    return env


def todo_cli(ws: todo.Workspace, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(todo.SKILL_DIR / "scripts" / "todo.py"),
                           "--home", str(ws.home), *args],
                          capture_output=True, text=True, env=run_env(ws), timeout=120)


def todo_status(ws: todo.Workspace) -> dict | None:
    """What `todo.py status --json` reports, or None if it cannot be read."""
    try:
        proc = todo_cli(ws, "status", "--json")
        return json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def append_runs_log(ws: todo.Workspace, text: str) -> Path:
    path = ws.state_dir / "runs.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.stat().st_size > RUNS_LOG_MAX_BYTES:
            os.replace(path, path.with_name("runs.log.1"))
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)
    return path


def notify_argv(ok: bool, brief: Path, log: Path, platform: str | None = None,
                which=shutil.which) -> list[str] | None:
    """The desktop-notification command for this platform, if its tool is present."""
    title = "Daily TODO ready" if ok else "Daily TODO run failed"
    body = str(brief) if ok else str(log)
    platform = platform or sys.platform
    if platform.startswith("linux") and which("notify-send"):
        return ["notify-send", title, body]
    if platform == "darwin" and which("osascript"):
        def quote(s: str) -> str:
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return ["osascript", "-e", f"display notification {quote(body)} with title {quote(title)}"]
    return None


def run_with_retry(attempt, succeeded, rollback, sleep, retries: int = 1,
                   delay: float = 0) -> int:
    """Run `attempt`; if the day is not recorded afterwards, roll back, wait, try again.

    Returns the number of attempts made if one succeeded, else 0. Success is decided by
    `succeeded()` (the day was recorded), never by the agent's exit code.
    """
    for n in range(1, retries + 2):
        attempt(n)
        if succeeded():
            return n
        rollback()
        if n <= retries:
            sleep(delay)
    return 0


def lock_is_ours(before_now: str | None, status: dict | None) -> bool:
    """True when the lock now present was taken after `before_now`, i.e. by our attempt."""
    if not status or not status.get("lock") or not before_now:
        return False
    lock = status["lock"]
    try:
        return (lock.get("mode") == "daily"
                and datetime.fromisoformat(lock["started"]) >= datetime.fromisoformat(before_now))
    except (KeyError, ValueError, TypeError):
        return False


# --------------------------------------------------------------------------------- run

def execute_agent(ws: todo.Workspace, cfg: dict, cmd: list[str], attempt: int) -> int:
    header = (f"\n=== {todo.iso(todo.get_now(todo.Zone(cfg['run']['timezone'])))} "
              f"attempt {attempt} ===\n$ {shlex.join(cmd)}\n")
    timeout = cfg["runner"]["timeout_minutes"] * 60
    try:
        proc = subprocess.Popen(cmd, cwd=str(ws.home), env=run_env(ws), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        append_runs_log(ws, header + f"could not start the agent: {exc}\n")
        note(f"could not start {cmd[0]!r}: {exc} (runner.agent in config.toml)")
        return 127
    try:
        out, err = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                break
            try:
                out, err = proc.communicate(timeout=10)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            out, err = "", ""
        out, err = out or "", err or ""
        code = 124
        err += f"\n[timed out after {cfg['runner']['timeout_minutes']} minutes and killed]\n"
    append_runs_log(ws, header + f"--- stdout ---\n{out}\n--- stderr ---\n{err}\n"
                                 f"--- exit {code} ---\n")
    return code


def cmd_run(args) -> int:
    ws, cfg, warnings = load(args)
    cmd, tool_warnings = build_command(ws, cfg)
    for w in warnings + tool_warnings:
        note(f"warning: {w}")
    if args.dry_run:
        print(f"# working directory: {ws.home}")
        print(f"# environment: TODO_HOME={ws.home}")
        print(f"# timeout: {cfg['runner']['timeout_minutes']} minutes; on failure: "
              f"todo.py abort --rollback, wait {cfg['runner']['retry_delay_seconds']}s, "
              f"try once more")
        print(shlex.join(cmd))
        return 0

    status = todo_status(ws)
    if status is None:
        note("cannot read `todo.py status`; is the workspace healthy? See the output of "
             f"`python3 {todo.SKILL_DIR}/scripts/todo.py status`")
        return 2
    if status.get("ran_today") and not args.force:
        append_runs_log(ws, f"\n=== {status['now']} skipped: today's run is already recorded "
                            f"===\n")
        print("Today's run is already recorded; nothing to do (use --force to run again).")
        return 0
    lock = status.get("lock")
    if lock and not lock.get("stale"):
        note(f"another {lock['mode']} run holds the lock since {lock['started']}; not starting")
        return 3

    zone = todo.Zone(cfg["run"]["timezone"])
    ws_brief = ws.brief(todo.get_now(zone).date().isoformat())
    log_path = ws.state_dir / "runs.log"
    delay = cfg["runner"]["retry_delay_seconds"]

    def attempt(n: int) -> None:
        execute_agent(ws, cfg, cmd, n)

    def succeeded() -> bool:
        s = todo_status(ws)
        return bool(s and s.get("ran_today"))

    before = {"now": status["now"]}

    def rollback() -> None:
        s = todo_status(ws)
        if lock_is_ours(before["now"], s):
            proc = todo_cli(ws, "abort", "--rollback")
            append_runs_log(ws, f"--- abort --rollback: exit {proc.returncode} "
                                f"{proc.stdout.strip()} {proc.stderr.strip()}\n")
        else:
            append_runs_log(ws, "--- no lock of ours to roll back\n")

    n = run_with_retry(attempt, succeeded, rollback, time.sleep, retries=1, delay=delay)
    if cfg["runner"]["notify"]:
        argv = notify_argv(bool(n), ws_brief, log_path)
        if argv:
            try:
                subprocess.run(argv, timeout=30, capture_output=True)
            except (OSError, subprocess.TimeoutExpired):
                pass
    if n:
        print(f"Daily TODO recorded for today (attempt {n}). Brief: {ws_brief}")
        return 0
    note(f"the daily run did not complete; see {log_path}")
    return 1


# ------------------------------------------------------------------------------ install

def systemd_quote(arg: str) -> str:
    """Quote one word for ExecStart=; also doubles % (specifiers) and $ (variables)."""
    arg = arg.replace("%", "%%").replace("$", "$$")
    if re.search(r'[\s"\'\\]', arg):
        return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return arg


def unit_value(text: str) -> str:
    """Escape a value used in Environment=KEY=value (specifiers only)."""
    return text.replace("%", "%%")


def service_path_dirs(cfg: dict) -> list[str]:
    dirs = []
    agent = shutil.which(cfg["runner"]["agent"])
    if agent:
        dirs.append(str(Path(agent).parent))
    dirs.append(str(Path(sys.executable).parent))
    dirs += [str(Path.home() / ".local" / "bin"), "/usr/local/bin", "/usr/bin", "/bin"]
    return list(dict.fromkeys(dirs))


def timeout_seconds(cfg: dict) -> int:
    r = cfg["runner"]
    return int(2 * r["timeout_minutes"] * 60 + r["retry_delay_seconds"] + 300)


def render_service(ws: todo.Workspace, cfg: dict, python: str, script: Path) -> str:
    path = ":".join(service_path_dirs(cfg))
    return "\n".join([
        "[Unit]",
        "Description=Daily TODO run (todo skill)",
        "",
        "[Service]",
        "Type=oneshot",
        f"WorkingDirectory={systemd_quote(str(ws.home))}",
        f"Environment={systemd_quote('TODO_HOME=' + unit_value(str(ws.home)))}",
        f"Environment={systemd_quote('PATH=' + unit_value(path))}",
        f"ExecStart={systemd_quote(python)} {systemd_quote(str(script))} run",
        f"TimeoutStartSec={timeout_seconds(cfg)}",
        "",
    ])


def render_timer(hhmm: str, weekdays: bool) -> str:
    calendar = f"{'Mon..Fri ' if weekdays else ''}*-*-* {hhmm}:00"
    return "\n".join([
        "[Unit]",
        f"Description=Run the daily TODO at {hhmm}{' on weekdays' if weekdays else ''}",
        "",
        "[Timer]",
        f"OnCalendar={calendar}",
        "Persistent=true",
        f"Unit={SERVICE_NAME}",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ])


def render_plist(ws: todo.Workspace, cfg: dict, python: str, script: Path, hhmm: str,
                 weekdays: bool) -> str:
    hour, minute = (int(x) for x in hhmm.split(":"))
    if weekdays:
        interval = [{"Weekday": d, "Hour": hour, "Minute": minute} for d in range(1, 6)]
    else:
        interval = {"Hour": hour, "Minute": minute}
    data = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [python, str(script), "run"],
        "WorkingDirectory": str(ws.home),
        "EnvironmentVariables": {"TODO_HOME": str(ws.home),
                                 "PATH": ":".join(service_path_dirs(cfg))},
        "StartCalendarInterval": interval,
        "StandardOutPath": str(ws.state_dir / "launchd.log"),
        "StandardErrorPath": str(ws.state_dir / "launchd.log"),
    }
    return plistlib.dumps(data).decode("utf-8")


def render_cron(ws: todo.Workspace, python: str, script: Path, hhmm: str, weekdays: bool) -> str:
    hour, minute = (int(x) for x in hhmm.split(":"))
    dow = "1-5" if weekdays else "*"
    return (f"{minute} {hour} * * {dow} TODO_HOME={shlex.quote(str(ws.home))} "
            f"{shlex.quote(python)} {shlex.quote(str(script))} run "
            f">> {shlex.quote(str(ws.state_dir / 'cron.log'))} 2>&1")


def systemd_dir() -> Path:
    return todo.xdg_config_home() / "systemd" / "user"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def systemctl_user_works() -> bool:
    if not shutil.which("systemctl"):
        return False
    try:
        return subprocess.run(["systemctl", "--user", "show-environment"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def choose_scheduler(requested: str) -> str:
    if requested != "auto":
        return requested
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux") and systemctl_user_works():
        return "systemd"
    return "cron"


def run_commands(cmds: list[list[str]], dry: bool) -> int:
    for c in cmds:
        print(("would run: " if dry else "running: ") + shlex.join(c))
        if not dry:
            proc = subprocess.run(c, capture_output=True, text=True)
            if proc.returncode != 0:
                note(f"`{shlex.join(c)}` failed: {proc.stderr.strip() or proc.stdout.strip()}")
                return 1
    return 0


def cmd_install(args) -> int:
    ws, cfg, warnings = load(args)
    for w in warnings:
        note(f"warning: {w}")
    hhmm = args.time
    if not RE_TIME.match(hhmm):
        raise todo.TodoError(f"--time {hhmm!r}: expected HH:MM on a 24-hour clock, e.g. 07:30")
    python = sys.executable
    script = Path(__file__).resolve()
    scheduler = choose_scheduler(args.scheduler)
    dry = args.dry_run
    if not shutil.which(cfg["runner"]["agent"]):
        note(f"warning: runner.agent {cfg['runner']['agent']!r} is not on PATH here; the "
             f"scheduled run will fail until it is installed or runner.agent is corrected")
    if dry:
        print(f"# dry run: nothing is written or started. Scheduler: {scheduler}")

    if scheduler == "systemd":
        base = systemd_dir()
        files = {base / SERVICE_NAME: render_service(ws, cfg, python, script),
                 base / TIMER_NAME: render_timer(hhmm, args.weekdays)}
        for path, text in files.items():
            print(f"\n--- {'would write' if dry else 'writing'} {path}\n{text}")
            if not dry:
                todo.write_atomic(path, text)
        rc = run_commands([["systemctl", "--user", "daemon-reload"],
                           ["systemctl", "--user", "enable", "--now", TIMER_NAME]], dry)
        if rc == 0 and not dry:
            print(f"\nInstalled. Check with: systemctl --user list-timers {TIMER_NAME}\n"
                  f"Runs are logged in {ws.state_dir / 'runs.log'}.\n"
                  f"To run while you are logged out: loginctl enable-linger $USER")
        return rc
    if scheduler == "launchd":
        path = launchd_plist_path()
        text = render_plist(ws, cfg, python, script, hhmm, args.weekdays)
        print(f"\n--- {'would write' if dry else 'writing'} {path}\n{text}")
        if not dry:
            todo.write_atomic(path, text)
        uid = os.getuid()
        rc = run_commands([["launchctl", "bootstrap", f"gui/{uid}", str(path)]], dry)
        if rc == 0 and not dry:
            print(f"\nInstalled. Check with: launchctl print gui/{uid}/{LAUNCHD_LABEL}")
        return rc
    # cron: print, never edit
    line = render_cron(ws, python, script, hhmm, args.weekdays)
    print("No supported user scheduler was found (or cron was requested). Nothing was "
          "installed. Add this line with `crontab -e`:\n")
    print(line)
    print("\ncron runs only while the machine is on; a run missed while it was off is not "
          "made up.")
    return 0


def cmd_uninstall(args) -> int:
    ws, cfg, _ = load(args)
    dry = args.dry_run
    sd = [systemd_dir() / SERVICE_NAME, systemd_dir() / TIMER_NAME]
    plist = launchd_plist_path()
    if any(p.exists() for p in sd):
        cmds = [["systemctl", "--user", "disable", "--now", TIMER_NAME]]
        rc = run_commands(cmds, dry)
        for p in sd:
            print(("would remove " if dry else "removing ") + str(p))
            if not dry and p.exists():
                p.unlink()
        rc |= run_commands([["systemctl", "--user", "daemon-reload"]], dry)
        return rc
    if plist.exists():
        rc = run_commands([["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"]], dry)
        print(("would remove " if dry else "removing ") + str(plist))
        if not dry:
            plist.unlink()
        return rc
    print("Nothing to uninstall: no todo-daily systemd unit or launchd agent was found. "
          "If you added a cron line, remove it with `crontab -e`.")
    return 0


def cmd_show(args) -> int:
    ws, cfg, _ = load(args)
    found = False
    for path in (systemd_dir() / SERVICE_NAME, systemd_dir() / TIMER_NAME, launchd_plist_path()):
        if path.exists():
            found = True
            print(f"--- {path}\n{todo.read_text(path)}")
    if (systemd_dir() / TIMER_NAME).exists() and shutil.which("systemctl"):
        try:
            proc = subprocess.run(["systemctl", "--user", "list-timers", TIMER_NAME,
                                   "--no-pager"], capture_output=True, text=True, timeout=10)
            print(proc.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not found:
        print("Not installed (no todo-daily systemd unit or launchd agent). "
              "Run `schedule.py install`.")
    log = ws.state_dir / "runs.log"
    print(f"\nrun log: {log} ({'exists' if log.exists() else 'no runs yet'})")
    return 0


# -------------------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", metavar="PATH", default=argparse.SUPPRESS,
                        help="workspace directory (default: $TODO_HOME, pointer file, ~/todo)")
    p = argparse.ArgumentParser(prog="schedule.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--home", metavar="PATH", default=None, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    s = sub.add_parser("run", parents=[common], help="the unattended run a scheduler calls")
    s.add_argument("--dry-run", action="store_true", help="print the agent command and exit")
    s.add_argument("--force", action="store_true",
                   help="run even if today's run is already recorded")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("install", parents=[common], help="install a daily timer")
    s.add_argument("--time", default="07:30", metavar="HH:MM")
    s.add_argument("--weekdays", action="store_true", help="Monday to Friday only")
    s.add_argument("--dry-run", action="store_true",
                   help="print every file and command; change nothing")
    s.add_argument("--scheduler", choices=["auto", "systemd", "launchd", "cron"],
                   default="auto", help="override detection")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("uninstall", parents=[common], help="remove the daily timer")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_uninstall)

    s = sub.add_parser("show", parents=[common], help="show what is installed")
    s.set_defaults(fn=cmd_show)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except todo.TodoError as exc:
        print(f"schedule.py: {exc.message}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
