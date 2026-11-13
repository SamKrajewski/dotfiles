# Cost and routing

Even with every section in place, the talk puts a review at $3 to $20. The
fix is to spend the expensive model only where it matters (the talk's figure:
about 20% of tokens on frontier models) and to stop exploring when the budget
for the depth is spent.

## Model tiers by subtask

| Subtask | Tier | Config key |
|---|---|---|
| Triage, author detection, file reading, KB upkeep, context ranking, de-duplication | small | `models.small` |
| Clicking through UI flows (level 4) | lightweight computer-use | `models.computer_use` |
| Bug analysis (step 5), intent judgement, verifying findings, final write-up | frontier | `models.frontier` |

How to apply this depends on the host:

- **Host can pick models per subagent or per call** (Jetski subagents with a
  `Model` parameter, Claude Code subagents, custom harnesses): run the small
  tier subtasks in cheap subagents and keep the frontier model for step 5 and
  the write-up. Guard the main model's context: hand it the ranked context
  pack, never raw search output or whole files.
- **Host runs a single model:** set the `models` keys blank, run everything
  with the current model, and lean on triage depth and the budgets below.

Every model swap goes through the evals (`subskills/evals.md`). A cheaper
model can quietly catch fewer bugs; the gate is what makes it safe to change.

## Depth and sizing

Depth is decided in step 1 and recorded in `change.json.triage`:

| Depth | Triggered by | What runs |
|---|---|---|
| `light` | tiny diff (`≤ light_max_lines` lines, `≤ light_max_files` files) **and** `project.kind: script` | steps 1, 3 (one line), 5, 7, 8; level 0–1 testing; no KB |
| `standard` | default; also the floor for `project.kind: application` | all eight steps; testing as far as the environment allows, at least level 1 when a test command exists |
| `deep` | any file under `depth.deep_paths` (auth, billing, migrations…), very large diffs (`≥ deep_min_lines` or `≥ deep_min_files`), or the floor for `project.kind: production` | all steps at full depth: inversion or blind-spot pass mandatory, level 2 tests for every critical/high candidate, level 3/4 when the prerequisites exist, stricter not_checked accounting |

The floor comes from the project, not the diff: a two-line change in a
production codebase still gets the deep pipeline, because the cost of a missed
bug there is not proportional to the diff size. Only `project.kind: script`
allows the light path.

Skipped files (`depth.skip_globs`, generated-file markers, binaries) are
listed in `change.json` and in the report but their hunks are not analysed.

## Budgets

`limits.budget_usd` holds a budget per depth (defaults 0.5 / 3 / 10, starting
points only). Track spend if the host reports it, otherwise track files read
and runtime minutes as a proxy. On hitting the budget: stop exploring, verify
what has been found, finish the report, and list what was skipped under
`coverage.not_checked`. A partial honest report beats an unfinished thorough
one.

## Guarding the main model's context

- Only the context pack (`tmp/context.md`) goes into the analysis, plus the
  diff and the intent. Never paste search results, directory listings, or
  whole files into the analysis step.
- Cap files read at `limits.max_context_files`; rank beyond that.
- For headless runs, `build_prompt.py --max-diff-chars` truncates enormous
  diffs and says so; prefer splitting such a change into deep per-area passes.

## Done when

The eval report shows cost per PR, and a cheaper routing passes the evals
gate (catch rate not lower, clean-control false positives not higher).
