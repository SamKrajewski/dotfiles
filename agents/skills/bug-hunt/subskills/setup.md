# Setup — first run in a repository

**Goal:** answer the questions that make every later review cheaper and
sharper, and record them in `.review/`. Do this once per repo, when
`collect_change.sh` reports that it created `.review/`, or when the user asks
to set the reviewer up.
**Writes:** `.review/config.yaml`, `.review/kb/`, `.review/flows.yaml`,
`.review/bug-catalog.local.md`, first eval cases.

Ask in small batches and offer defaults. Everything here can be skipped and
filled in later; say in the report what is still blank.

**Unattended first run** (no user in the conversation, a headless or eval
run): do not block. Set `inversion.self_family` to your own family (you know
it), leave everything else at the defaults, and list the six questions below
as unanswered under `coverage.not_checked` so the next attended review picks
them up.

## Ask the user

1. **What kind of project is this?** `script` (one-off tools; light reviews
   allowed), `application` (a real codebase; every change gets the standard
   pipeline), or `production` (user-facing or money/safety-bearing; every
   change gets the deep pipeline). Sets `project.kind`. Default:
   `application`.
2. **Is there an incident or postmortem list?** Each incident becomes a KB
   "Past incidents" line, a candidate eval case, and, grouped by root cause, a
   repo-specific class in `bug-catalog.local.md`. Without one, mine git
   history: `python3 <skill dir>/scripts/run_evals.py mine --clean`.
3. **Is a second, different-family agent CLI installed?** (Claude Code,
   Codex CLI, Gemini CLI.) If yes, record the headless command under
   `inversion.reviewers.<family>` using the contract in
   `references/inversion.md`. If no, the blind-spot pass is the fallback.
   Either way set `inversion.self_family` to the family of the agent running
   this skill.
4. **Which ticket and doc tools should be connected?** `context.tickets`
   (github, jira, linear, buganizer, none) and `context.docs` paths.
5. **How is the project built, tested and started from a clean checkout?**
   `testing.setup`, `testing.test`, `testing.start`, `testing.health_url`.
   One script that boots the app is what unlocks levels 3 and 4; if it does
   not exist, note it as the highest-value piece of setup work.
6. **Which paths deserve the deep pass regardless of size?** Extend
   `depth.deep_paths` (auth, billing, migrations, anything regulated) and
   `depth.skip_globs` (generated code, vendored code).

Write the answers into `.review/config.yaml` (keep the comments; they are the
documentation).

## Seed the knowledge base

Follow "Building the KB" in `references/context.md`: 8 to 30 entries from
architecture docs, the incident list, and the module boundaries; each entry's
**Invariants** verified against the code. For a first session, two or three
entries for the subsystems the current change touches are enough; later
reviews add the rest through `kb_updates`.

## Seed the flow map

If there is a UI, write `.review/flows.yaml` from `templates/flows.yaml`:
the three to five flows that matter most, the paths that trigger them, and an
expectation about layout at 390×844 for each.

## Seed the evals

Aim for 20+ bug cases and 10 clean controls over time; start with what
exists. `subskills/evals.md` has the procedure, including synthetic cases for
classes with no real example. Run the baseline once the first cases exist, so
later prompt and model changes have something to be compared against.

## Done when

- `project.kind` and `inversion.self_family` are set.
- The three questions (incidents, second CLI, ticket/doc tools) are answered
  or explicitly deferred in the config comments.
- At least the KB entries for the current change exist, and the test command
  is recorded if one exists.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
