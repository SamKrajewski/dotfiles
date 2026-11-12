# Configuration reference

Settings live in `<home>/config.toml`, created from `assets/config.example.toml` by
`todo.py init`. Every key is optional and has a default, so a three-line file works.
`todo.py begin` checks the file each run: a value of the wrong type or an unknown choice
stops the run and names the key, while an unknown key is ignored with a warning (so a typo
does not silently change behaviour).

The file is also the only place that decides which subskills run.

## `schema`

`schema = 1`. The only version that exists. Leave it.

## `[run]`

| Key | Default | Meaning and when to change it |
|---|---|---|
| `timezone` | `"local"` | `"local"` or an IANA name such as `"Europe/Berlin"`. All dates, the weekday and the windows follow it. Set it explicitly if the machine's zone is not where you live. |
| `max_lookback_days` | `7` | The furthest back any `since-last-run` window reaches. After a holiday you would otherwise get a flood; raise it only if you want to recover a longer gap. |
| `lock_stale_minutes` | `90` | A lock held longer than this is taken to be from a dead run and is removed (the next run is told `previous_run_incomplete`). Interactive sessions use the smaller of this and 15. Raise it if your runs are slower. |

## `[intake]`

How findings from sources become tasks.

| Key | Default | Meaning and when to change it |
|---|---|---|
| `mode` | `"auto-high"` | `"confirm-all"`: every inferred task waits in `## Proposed` until you accept it. `"auto-high"`: tasks explicitly assigned to or promised by you are added and listed as new so you can veto them; the rest are proposed. `"auto-all"`: everything is added except low-confidence guesses. Start with `confirm-all` if you do not yet trust a new source. |
| `proposal_ttl_days` | `7` | A proposal nobody answers for this long expires into `## Dismissed`, and is named in the brief so nothing vanishes unseen. |
| `dismissed_keep_days` | `21` | Rejected source items are remembered this long so they are not proposed again. Keep it at least as long as your longest `rolling` window. |

## `[focus]`

| Key | Default | Meaning and when to change it |
|---|---|---|
| `max_items` | `5` | The most items in "Focus today". Lower it if the brief feels like a to-do list again. |
| `stale_after_days` | `5` | An open task with no mention in the last this-many log entries is asked about ("keep, park or drop?"). Counted in run-days, and capped at `history.log_keep_days` (a warning says so if it was clamped), since the log cannot show more. |
| `due_soon_days` | `3` | Open tasks due within this many days (or overdue) are listed for a priority check. |

## `[history]`

These caps are what keep the files the run reads small.

| Key | Default | Meaning and when to change it |
|---|---|---|
| `log_keep_days` | `7` | How many dated entries stay in `log.md`. Older ones move to `archive/log-YYYY-MM.md`, which a run never reads. |
| `brief_keep_days` | `7` | How many briefs, and their `drafts/` folders, stay. Older ones move to `archive/`; a draft folder that a task still points to stays. |
| `backup_keep` | `14` | How many pre-run backups of `TODO.md` and `log.md` are kept in `.state/backups/`. These are what `todo.py restore` offers. |

## `[automation]`

| Key | Default | Meaning and when to change it |
|---|---|---|
| `mode` | `"prepare"` | `"prepare"`: draft replies, agendas and lookups into `drafts/`. `"off"`: prepare nothing. |
| `max_per_run` | `5` | The most items prepared per run. More is offered in one line under "Needs your input". |
| `allow_actions` | `[]` | Subskill actions allowed to run unattended, as `"<subskill>.<action>"`, for example `["gmail.create_draft"]`. Sending, replying, accepting, declining, posting, sharing, paying and deleting are never run unattended whatever is listed; listing one only earns a warning. |

## `[runner]`

Used by `scripts/schedule.py` for the unattended run. See `scheduling.md`.

| Key | Default | Meaning and when to change it |
|---|---|---|
| `agent` | `"claude"` | The executable that is started. Point it at a wrapper script to use another agent. |
| `model` | `""` | Empty means the agent's default. A smaller model is usually enough and cheaper for a daily run. |
| `max_budget_usd` | `0` | A spending cap per run in US dollars. `0` means no cap; a cap is worth setting. |
| `timeout_minutes` | `30` | A run still going after this long is killed, rolled back, and retried once. |
| `notify` | `true` | Desktop notification when the brief is ready or the run failed. |
| `retry_delay_seconds` | `600` | Wait before the one retry after a failed run. |
| `extra_allowed_tools` | `[]` | Permission rules for the unattended run beyond the base set and the subskills' own. `{skill}` and `{home}` are filled in. |

## `[[subskills]]`

One block per source, run in the order written. A subskill runs only if it appears here and
is enabled.

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Lowercase letters, digits and hyphens, unique, not `create-subskill`, not starting with `_`. Also the directory name. |
| `enabled` | `true` | `false` keeps the block but skips the source. |
| `path` | `""` | Where the subskill lives: absolute, `~/…`, or relative to the workspace. A directory holding `SKILL.md`, or the file itself. Empty means `<home>/subskills/<name>/` first, then the built-in `<skill>/subskills/<name>/`. |
| `window` | `"since-last-run"` | `"since-last-run"`: from this source's last successful collection until now (right for mail). `"rolling"`: always the last `lookback_days` (right for notes that are edited afterwards). |
| `lookback_days` | `run.max_lookback_days` | Rolling windows only. A warning appears if it exceeds `history.log_keep_days`, because items older than the log remembers may be reported again. |
| `max_items` | `15` | The most items this source reports per run. |
| `allowed_tools` | `[]` | Permission rules the unattended run needs for this source. `{skill}`, `{home}` and `{subskill_dir}` are filled in. |
| `[subskills.params]` | `{}` | Settings for the subskill itself, passed through as written. Each subskill's `SKILL.md` lists what it reads. |

A subskill whose file cannot be found is left out of the run with a warning, not an error,
so one broken entry does not cost you the brief.

### A full example

```toml
[[subskills]]
name = "gmail"
enabled = true
window = "since-last-run"
max_items = 15
allowed_tools = ["mcp__claude_ai_Gmail"]

[subskills.params]
owner_names = ["Jo Rivera", "jo@example.com"]
ignore_senders = ["noreply@", "notifications@"]
```

This runs the `gmail` subskill (the workspace copy if there is one, else the built-in), reads
mail since the last successful run, reports at most 15 items, and lets the unattended run use
the Gmail connector's tools. If `automation.allow_actions` also contains `"gmail.create_draft"`,
the run may save reply drafts into Gmail without asking; it can still never send them.
