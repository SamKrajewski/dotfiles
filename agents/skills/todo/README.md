# todo: a daily TODO skill

Keeps a running list of your goals, subgoals and prioritised tasks. Every morning it
pulls new information from your own sources (calendar, mail, meeting notes, anything
you connect), reviews what happened since yesterday, follows up on next steps, prepares
what it can (draft replies, agendas, lookups), and writes a one-screen brief.

Everything about you lives in a workspace (default `~/todo`), in plain Markdown you can
read and edit. The skill directory itself holds no personal data.

## Install

Link this directory into your agent's skills directory, for example:

```bash
ln -s /path/to/this/skill ~/.claude/skills/todo
```

Python 3.11 or newer is the only requirement (standard library only).

## First use

Ask the agent: "set up my todo". It creates the workspace, asks for your two to five
main goals, shows you the available sources, and offers to schedule the morning run.
Then ask for "my daily todo" to do the first run together.

## Where things live

| In `~/todo` (or `$TODO_HOME`) | What it is |
|---|---|
| `TODO.md` | Goals, tasks, priorities. Edit it freely; your edits win. |
| `log.md` | Short dated facts about the last week. |
| `briefs/` | One brief per day. `drafts/` holds what was prepared for you. |
| `config.toml` | Settings, and the list of sources that run. |
| `context.md` | Standing facts and preferences, yours alone. |
| `subskills/` | Your own connectors. `archive/` and `.state/` are bookkeeping. |

## Adding a source

A source is a "subskill". Tell the agent "connect my calendar" (or mail, or a folder of
notes) and it follows `subskills/create-subskill/SKILL.md` with you: it probes access,
writes the connector, registers it in `config.toml`, and tests it. `local-notes` works
out of the box. `google-calendar`, `gmail` and `gdocs-meeting-notes` are examples that
have not been verified against a live account; test them before relying on them.

## Scheduling

From this directory (or with the full path):

```bash
python3 scripts/schedule.py install --dry-run     # see what would be installed
python3 scripts/schedule.py install --time 07:30  # systemd timer, launchd agent or a cron line
```

The unattended run uses an explicit tool allowlist and never bypasses permissions. See
`references/scheduling.md`.

## Undoing a run

Every run starts from a backup. `python3 scripts/todo.py restore --list` shows them, and
`python3 scripts/todo.py restore` puts back `TODO.md` and `log.md` (and the run records, so
the next run collects again what the undone run had seen) from before the latest run.

## More

`SKILL.md` is the workflow the agent follows. `references/` has the file formats
(`state-format.md`), the connector interface (`subskill-contract.md`), every setting
(`config.md`) and scheduling.
