# Making it run every morning

`scripts/schedule.py` does two jobs: `run` is the unattended daily run that a scheduler
calls, and `install` puts that call on a timer. Everything it needs comes from
`config.toml`; the `runner` section is explained in `config.md`.

## Install

Show the user what will be installed first, then:

```bash
python3 <skill>/scripts/schedule.py install --dry-run            # prints every file and command
python3 <skill>/scripts/schedule.py install --time 07:30        # every day (the default)
python3 <skill>/scripts/schedule.py install --time 07:30 --weekdays
```

`--dry-run` writes nothing and starts nothing; read its output before the real install.

| Platform | What `install` does |
|---|---|
| Linux with a working `systemctl --user` | Writes `todo-daily.service` and `todo-daily.timer` to `${XDG_CONFIG_HOME:-~/.config}/systemd/user/`, then `daemon-reload` and `enable --now todo-daily.timer` |
| macOS | Writes a launchd agent, `~/Library/LaunchAgents/com.todo-skill.daily.plist`, and bootstraps it |
| Anything else | Prints a crontab line and stops. It does not edit your crontab. |

`--scheduler systemd|launchd|cron` overrides the detection. To change the time, run
`install` again with the new `--time`; it replaces the unit files. `schedule.py show`
prints what is installed, and `schedule.py uninstall` removes it (`uninstall` also takes
`--dry-run`).

## Check that it ran

- `~/todo/.state/runs.log` (or `<home>/.state/runs.log`) records every attempt: the
  command, what the agent printed, and its exit code. It is trimmed when it passes 1 MB.
- `systemctl --user list-timers todo-daily.timer` shows when it last fired and when it
  fires next. `systemctl --user status todo-daily.service` shows the last run's result.
- `python3 <skill>/scripts/todo.py status` says whether today's run is recorded
  (`ran today`). That, not the agent's exit code, is what counts as success: the run
  has happened only if `finish` passed.
- With `runner.notify = true`, a desktop notification says "Daily TODO ready" with the
  brief's path, or "Daily TODO run failed" with the log's path.

If a run fails, `schedule.py` rolls `TODO.md` and `log.md` back to their pre-run state,
waits `runner.retry_delay_seconds`, and tries once more. It only rolls back a lock that
its own attempt took, so it never undoes an interactive session you had open. If a run
for today is already recorded when the timer fires (you ran it by hand), it does nothing;
`schedule.py run --force` runs it again.

## When the machine was off: `Persistent`

The timer is written with `Persistent=true`. systemd then remembers when the timer last
fired, and if the computer was off or asleep at 07:30 it runs the job once, at the next
start, instead of skipping the day. Without it a laptop that is closed at 07:30 would
simply miss that morning. (cron has no equivalent, and says nothing when a run is missed.)

User timers only run while your user manager is running, which normally means while you
are logged in. To have the run happen on a machine you are not logged in to, for example
a home server, enable lingering once: `loginctl enable-linger $USER`.

## Why there is an allowlist

The unattended agent reads your mail, calendar and documents, which other people write,
and nobody is watching. So it is never started with permissions bypassed. `run` starts
the agent with `--permission-mode acceptEdits` and an explicit `--allowedTools` list:

- the file tools (`Read`, `Write`, `Edit`, `Glob`, `Grep`) and the ability to start
  subagents (`Agent`, `Task`),
- one shell command, `python3 <skill>/scripts/todo.py *`,
- and whatever each enabled subskill declares in its `allowed_tools`, plus
  `runner.extra_allowed_tools`.

Anything not on that list is refused. That is the reason a new source needs an
`allowed_tools` entry before it works at 07:30, even if it works when you test it in
conversation: the conversation can ask you, the timer cannot. `todo.py allowed-tools`
prints the final list; `schedule.py run --dry-run` prints the whole command.

The prompt tells the agent to call `todo.py` by its absolute path with no `cd`, because
only that exact form matches the permitted command.

## Sign in to the connectors once

Connectors such as Gmail, Calendar and Drive must be signed in in an interactive session
first. The unattended run cannot complete a sign-in. A source that is not signed in comes
back `unavailable` ("connector not signed in"), and the symptom is a source marked
`unavailable` in the brief's Sources section, then a line under "Needs your input" once
it has happened twice in a row. The fix is to open an interactive session, sign in, and
test the source (see `subskills/create-subskill/SKILL.md`).

## Using another agent

`runner.agent` names the executable. The command `schedule.py` builds follows Claude
Code's flags (`-p`, `--add-dir`, `--permission-mode`, `--allowedTools`, `--model`,
`--max-budget-usd`). For another agent CLI, point `runner.agent` at a small wrapper
script that accepts those arguments and calls your agent in its own way: pass the prompt
(the argument after `-p`), give it read access to the skill directory and write access to
the workspace, and restrict its tools to the allowlist if it supports one. Whatever it
does, the run only counts once `todo.py finish` has passed. If the agent cannot restrict
its tools, do not schedule it with real accounts connected. `schedule.py run --dry-run`
shows exactly what the wrapper will receive.

## Cloud schedulers

Hosted schedulers (a cloud agent that runs on a cron schedule) start from a fresh
machine, so they cannot see `~/todo`, your local notes, or a sign-in that lives on this
computer. This skill keeps its state in a local workspace on purpose, and for that reason
it is not supported on a cloud scheduler as it stands. Making it work there would mean
moving the workspace into storage the scheduler can reach, running every source through
connectors available there, and deciding how its run-lock and backups survive; none of
that is built.
