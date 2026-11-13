---
name: bug-hunt
description: Reviews a pull request, branch, commit range, jj change, CL, or pasted diff for real bugs and intent mismatches, and skips nitpicks. An eight-step pipeline with one subskill per step: collect the change, detect whether a human or a coding agent (Claude, GPT, Gemini) wrote it and route to a different-family reviewer or a blind-spot pass, state the intent from the PR/ticket/docs, load knowledge-base context, hunt a fixed catalog of bug classes, run tests or the app as far as the sandbox allows, filter hard, and report findings with stable IDs and plain-language explanations; re-runs update prior findings instead of repeating them. Needs only shell, git or jj, and file access. Use when asked to hunt bugs, review code, a PR, a CL, a branch, or a diff, to check whether a change does what was asked, to re-review after fixes, to set up the per-repo .review/ knowledge base, or to build or run review evals. Don't use for style or formatting passes, writing CL descriptions, or posting replies in Critique or GitHub.
---

# Bug hunt

Find the bugs that matter, say what was asked and whether the code does it,
and report both so that anyone can follow the reasoning. Everything else
(style, naming, coverage wishes) is noise this skill deliberately does not
produce: noise buries the one comment that matters, and coding agents "fix"
every comment they see.

A baseline agent with a diff and "review this" fails five ways: it misses
bugs, misses context, costs $3 to $25 per PR, nitpicks, and finds "new" bugs
on every re-run. Each step below exists to fix one of those.

## The pipeline

Always in this order. Read a step's subskill when you reach it, not before.

| # | Step | Subskill | Produces (under `.review/tmp/`) |
|---|------|----------|----------------------------------|
| 1 | **Collect** the change, decide depth, detect re-review | `subskills/01-collect.md` | `change.json` |
| 2 | **Author** detection; pick the reviewer model | `subskills/02-author.md` | `author.json` |
| 3 | **Intent**: what was asked, from PR, tickets, docs, user | `subskills/03-intent.md` | `intent.md` |
| 4 | **Context**: knowledge base, invariants, consumers | `subskills/04-context.md` | `context.md` |
| 5 | **Analyse**: bug hunt, intent check, blast radius | `subskills/05-analyse.md` | `draft.json` |
| 6 | **Run** tests, throwaway tests, the app, the browser | `subskills/06-run.md` | updated `draft.json` |
| 7 | **Filter** hard: reportability, severity, caps | `subskills/07-filter.md` | final `draft.json` |
| 8 | **Report** and save state | `subskills/08-report.md` | `review.json`, `review.md`, `state/` |

Step 5 is the bug-finding prompt. It lives only in `subskills/05-analyse.md`
and is the same text whether you run it yourself or hand it to another
model's CLI, so it can be tuned on its own and measured with the evals.

Procedures outside the per-change pipeline:

| File | Use it when |
|------|-------------|
| `subskills/setup.md` | First run in a repo, or the user wants the reviewer configured (project kind, incidents, second CLI, tickets, build/start commands) |
| `subskills/evals.md` | Building or running the eval set; required before any change to the prompt, models or routing |

## Sizing the review

Depth is set in step 1 from the diff and the project, and recorded in
`change.json.triage`. The project sets a floor; the diff can only raise it.

| Depth | When | What runs |
|-------|------|-----------|
| **light** | `project.kind: script` and a tiny diff | steps 1, 3 (one line), 5, 7, 8; testing level 0–1; no knowledge base |
| **standard** | any change in a real codebase (`project.kind: application`, the default) | all eight steps; level 1 testing whenever a test command exists, level 2 for critical/high findings |
| **deep** | `project.kind: production`, or any diff touching auth, billing, migrations, or very large | all steps at full depth: inversion or blind-spot pass, level 2 for every critical/high, levels 3–4 when the start script and browser tool exist |

A two-line change in a production codebase gets the deep pipeline. Only
standalone scripts and throwaway tools get the light one, and even then
inputs, outputs and the intent are checked. Never lower a depth on your own;
if the user asks for a lighter pass on production code, explain the floor and
get an explicit yes.

## Where things live

```
<skill dir>/
  SKILL.md  subskills/  references/  scripts/  templates/
.review/                      per repo, created by step 1; commit all but state/ and tmp/
  config.yaml  kb/  flows.yaml  bug-catalog.local.md  evals/cases/  state/  tmp/
```

In a CitC or Piper workspace, set `CODE_REVIEW_DIR` to a local path (for
example `~/.cache/bug-hunt/<repo>`) before step 1: CitC is world-readable
and keeps every write in snapshots, and `collect_change.sh` refuses to create
`.review/` there without it.

For another agent, copy or symlink this directory into its skills folder (for
example `.claude/skills/bug-hunt/`); for agents without skills, point to
this `SKILL.md` from the project's `AGENTS.md`.

## Rules for every step

- **Only shell, git (or jj) and file access are required.** `gh`, a browser
  tool, subagents, a second agent CLI, and ticket connectors are used when
  present. When one is missing, the report says what was skipped because of
  it; it never pretends.
- **Honesty about coverage.** Every report lists what was not checked and the
  runtime level reached. No findings means "nothing that passes the
  reportability test", never "no bugs".
- **No nitpicks.** A finding names the input or state, the wrong outcome, and
  who is hurt, or it is not reported (`references/nitpicks.md`).
- **Plain language, no assumed expertise.** Every finding carries a
  step-by-step explanation that defines its terms first and uses concrete
  values, next to the technical description (`references/explaining.md`). A
  finding about string encoding should be followable by someone who has never
  heard of UTF-8.
- **Safety.** Sandboxes only; no production, no real credentials; never push
  to, amend or rebase the branch under review; never post to a code host
  unless asked.
- **Stable across runs.** Finding IDs hash class, file and the quoted code,
  so the same head yields the same IDs, and dismissed findings stay dismissed.
- **Numbers from the talk are vendor claims** (10% from inversion, 80%
  fingerprint coverage, $3–$20 per review). Confirm them with your own evals
  before relying on them.

## Supporting files

| File | Contents |
|------|----------|
| `references/bug-catalog.md` | The 14 bug classes: what to look for, how to confirm, example |
| `references/nitpicks.md` | Reportability test, never-report list, severity, confidence, caps |
| `references/explaining.md` | The plain-language method with a worked string-semantics example |
| `references/output.md` | `change.json`, `draft.json`, `review.json` schemas; stable IDs; state and re-review |
| `references/inversion.md` | Author fingerprint table (machine-read), blind spots, routing, headless contract |
| `references/context.md` | Knowledge-base format, review-time procedure, freshness, building it |
| `references/testing.md` | Runtime levels 0–4, prerequisites, per-level procedure, safety |
| `references/routing.md` | Model tiers per subtask, depth rules, budgets, guarding context |
| `scripts/collect_change.sh` | Step 1: git / jj / diff file → `change.json`, creates `.review/` |
| `scripts/detect_author.py` | Step 2: family, confidence, signals, route |
| `scripts/build_prompt.py` | Step 5 headless: fills the prompt from `05-analyse.md` |
| `scripts/review_report.py` | Steps 7–8: `validate`, `finalize`, `render`, `dismiss`, `id` |
| `scripts/run_evals.py` | Evals: `list`, `mine`, `run` (with `--gate`), `compare` |
| `scripts/test_scripts.py` | Self-test for the scripts and the fingerprint table; run after editing either |
| `templates/` | `config.yaml`, `kb-entry.md`, `kb-index.md`, `flows.yaml`, `eval-case.yaml`, `bug-catalog.local.md` |

Scripts are Python 3 standard library only (PyYAML is used when installed).
Run them with the paths shown in each subskill; `<skill dir>` is the directory
containing this file.

## Custom instructions

Every file in this skill ends with a section like this one. Anything written
there takes precedence over the defaults above it. Rules placed here apply to
every step.

<!-- Add your own review-wide rules below this line. -->
