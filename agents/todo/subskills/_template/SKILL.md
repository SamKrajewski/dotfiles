---
name: your-subskill-name
description: One or two sentences. Which source this reads and what it reports. The first sentence is what `todo.py status` shows next to the name.
---

# Your source connector

One line: what this reads, and that Collect never changes anything.

## Requirements

What this needs: the tools, CLI, credentials or files, named exactly as you found them
while probing. Then one cheap, read-only check that proves they are available, and what
to return when it fails (`unavailable`, with a note saying what the user should do).

Params this subskill reads from `config.toml`, as a table: name, meaning, default.

## Collect

How to fetch what is new or changed in `window.since` → `window.until`.

What counts as something the user must do: concrete rules, with an example or two.

What to ignore: the senders, folders, labels, projects or kinds of item that are noise.

How each item's `ref` is built: source, a quoted label, a date, a link or id. Use only
parts that do not change when the item is edited or answered, so the same item always
gets the same `ref`.

How to decide `confidence` (`high` only when the item is addressed to, assigned to or
promised by the user) and which `kind` each case maps to (`action`, `update`, `event`,
`deadline`, `fyi`).

Return the findings block from `references/subskill-contract.md`, and nothing else.

## Lookup

(Optional: delete this section if the source holds nothing worth fetching on demand.)
Which questions this can answer, how to search for the answer, and what to say when it
is not there (`not-found`; never fill a gap from general knowledge).

## Actions

(Optional: delete this section if the connector only reads.) One `###` heading per
action, in `snake_case`. Under each: what it does and needs, what it changes outside
the workspace, and how to undo it. Nothing that reaches other people or cannot be
undone belongs here; prepare those for the user instead.

### example_action
Does what, on what input.
Changes: what outside the workspace.
Undo: how.

## Notes

(Optional.) Quirks of the source, rate limits, known gaps, and anything a person
debugging this in six months would want to know.
