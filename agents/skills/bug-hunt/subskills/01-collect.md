# Step 1 — Collect the change

**Goal:** turn "review this" into one file, `tmp/change.json`, that every later
step reads: SHAs, branch, changed files, diff, commits with trailers, the PR
if one exists, the prior review state, and a depth decision.
**Writes:** `.review/tmp/change.json` (and the `.review/` skeleton on first run).
**Runs:** every depth.

## Decide what is under review

| The user says | Base and head |
|---|---|
| nothing specific, git repo, uncommitted edits | default: merge-base with the default branch → working tree (`head_sha` gets a `+dirty-…` suffix) |
| nothing specific, git repo, clean | merge-base with the default branch → `HEAD` |
| a branch or PR | `collect_change.sh main feature-branch` (`origin/main` when the remote is the reference); with `gh` the PR title, body and labels come along |
| a commit or range | `collect_change.sh <base> <head>` |
| nothing specific, jj workspace | `@`, or `@-` when `@` is empty; base = `fork_point(trunk() \| head)` |
| a jj revision or a stack | `collect_change.sh 'fork_point(trunk() \| xyz)' xyz` |
| a pasted or attached diff | `collect_change.sh --diff-file patch.diff --title "..." --body "..."` |

When in doubt about scope, ask one question; reviewing the wrong range wastes
the whole run.

## Run it

```bash
# CitC / Piper workspaces are world-readable and snapshot every write: keep the
# state outside the workspace. The script refuses to create .review/ in one.
export CODE_REVIEW_DIR=~/.cache/bug-hunt/<repo-name>   # only in CitC

bash <skill dir>/scripts/collect_change.sh [BASE] [HEAD]
```

The script prints a summary (range, files reviewed and skipped, depth and
reasons, re-review status, notes). Read `change.json` once: the `diff` field
is the input to step 5, so load it into context exactly once and refer back to
it rather than re-reading the file.

First run in a repo: the script says `initialised … (first run)` when it had
to create `config.yaml` (a message about completing the skeleton means a
config already existed and was kept). On a true first run with the user
present, go to `subskills/setup.md` before continuing. Unattended (headless,
evals, user away): keep the defaults, continue, and list the unanswered setup
questions under `coverage.not_checked`.

## Depth

`triage.depth` combines the diff (tiny, normal, large or touching
`depth.deep_paths`) with the project floor (`project.kind`). Rules:

- You may raise the depth (the user says this is production code, the change
  touches money or auth that the globs missed). Never lower it; if the user
  asks for a light review of production code, explain the floor and ask them
  to confirm in writing before proceeding.
- `light` is only reachable for `project.kind: script`. A small change inside a
  real codebase still gets the standard pipeline, because the cost of a missed
  bug there has nothing to do with the diff size.
- The depth decides which later steps run and how far testing climbs; see the
  sizing table in `SKILL.md` and `references/routing.md`.

## Re-review

If `prior` is set, a previous run reviewed this branch:

- `rereview.unchanged: true` — same head as last time. Re-running must
  reproduce the same finding IDs and raise nothing new; report that, and stop
  unless the user wants a fresh full pass.
- `rereview.diff` present — analyse only the new commits in step 5, then
  re-check every prior finding against the current code (resolved,
  still-present). Dismissed findings are filtered automatically.
- `rereview.note` says the branch was rebased or amended — review the full
  change again; prior findings are still matched by ID.

## Carry forward

Note for the report: skipped files and why (`changed_files[].skipped`),
untracked files that were not part of the diff, `pr_error` if `gh` failed,
and any `notes` from the script. These all belong under
`coverage.not_checked` unless a later step covers them.

## Done when

- `tmp/change.json` exists for the intended range, and you have stated the
  range and the depth to the user in one line.
- You know whether this is a first review, a re-review of new commits, or an
  unchanged head.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
