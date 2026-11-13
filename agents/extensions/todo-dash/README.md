# TODO Dash

A Jetski UI plugin for the daily **todo** skill. It renders the skill's workspace
(`~/todo` by default) as a dashboard and lets you make the edits the skill already
expects you to make by hand.

## What you see

| Tab | Contents |
|---|---|
| **Today** | Focus list (priority, then due date), due-soon and waiting-on-others lists, proposals to triage, the latest brief's "Needs your input" / "Prepared for you", run status |
| **Goals** | One card per mainline goal: priority + pin, due date, "done when", a progress bar (done ÷ (done + open)), subgoals with their own progress, tasks, closed tasks, quick-add |
| **Inbox** | Proposed items (accept into a goal / reject with a reason), parked items, dismissed references |
| **History** | Closed tasks (filter by goal) and the dated log timeline |
| **Docs** | Every document a task or brief points at: Google Docs, mail, conversations, drafts, briefs |
| **Brief** | Any kept brief, rendered; plus `context.md` and the raw `TODO.md` |

The bar at the bottom sends a *quick update* to the agent in the current
conversation ("done with T12", "add: call Dana by Friday"). **Run daily** asks the
agent to do the full daily run.

## How edits work

Priority, pin (`P1!`), done (`[x]`), drop (`[-]`), park, accept/reject a proposal, move
to a goal and quick-add are written **directly into `TODO.md`**, in the exact line format
the skill specifies, as if you had typed them. The skill's next run (or quick update)
sees them as *your edits*, which always win, and logs them. The dashboard never writes
`log.md`, briefs, or `.state/`.

- Edits are refused while a run holds `.state/run.lock` (a banner says so).
- New task ids come from the highest id ever seen (file, logs, archives, the skill's
  counter), so ids are never reused.
- Parsing is delegated to the skill's own `scripts/todo.py`, so the dashboard and the
  linter can never disagree about the format.

## Goal progress

`TODO.md` only holds open tasks, so the dashboard keeps a small index of every task it
has seen (`<sidecar data dir>/task_index.json`): id, title, goal, subgoal, first and last
seen, and how/when it closed (from `log.md`'s `done:` / `dropped:` lines). Progress per
goal and subgoal is `done ÷ (done + open)`. Tasks closed before the dashboard first ran
appear in History without a goal.

## Requirements

- The todo skill at `~/.gemini/config/skills/todo` or `~/.config/agents/skills/todo`
  (`TODO_SKILL_DIR` overrides), with a workspace initialised by `todo.py init`.
- Python 3.11+, standard library only.

## Enable

Jetski Web → **UI Plugins** → enable **TODO Dash**. Open it from a conversation's **+**
menu (side pane) or from the left sidebar (full page). Logs:
`~/.gemini/jetski/sidecar_data/todo-dash/dash/logs/sidecar.log`.

## Development

```bash
cd ~/.gemini/config/plugins/todo-dash/sidecars/dash
ANTIGRAVITY_SIDECAR_WEB_PORT=18765 python3 server.py --home /path/to/test/workspace
python3 server.py --home /path/to/test/workspace --dump   # state JSON
```

`?token=…` on the page URL is what the host passes; without
`ANTIGRAVITY_SIDECAR_TOKEN` set, POSTs are accepted unauthenticated (local dev only).
