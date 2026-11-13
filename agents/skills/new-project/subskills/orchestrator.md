# Subskill — The Orchestrator

**Use when:** Step 8.3, whenever a build is resumed (`.orchestrator/tasks.md` exists with unchecked tasks), and for the build of a feature (`add-feature.md` § 8).
**Role:** the layer between the PRD and the task agents. The orchestrator reads, routes, briefs, spawns, verifies and records. It is the only participant that sees everything. It never writes project code or tests, and it never settles a design question: those go to `amend.md`.

Everything the orchestrator knows is in a file, so a fresh orchestrator can take over at any time:

| File | Role | Who writes it |
|------|------|---------------|
| `agents/prd.md` § 5 | task definitions: law | nobody, after the freeze |
| `.orchestrator/tasks.md` | live checklist: `[ ]` pending, `[~]` running, `[x]` done, `BLOCKED(needs human): `, `HOLD: ` | the orchestrator; the user may reorder lines or add `HOLD: ` |
| `.orchestrator/context.md` | shared context read by every code and devops agent | the orchestrator, once at the start; later only by appending a dated note |
| `.orchestrator/progress.md` | append-only learnings | code and devops agents; the orchestrator on failures and decisions; the user with `HUMAN NOTE:` |
| `.orchestrator/briefs/<id>-<attempt>.md` | the exact brief each attempt received | the orchestrator |
| `.orchestrator/worktrees/<id>/` | one checkout of `scaffold` per test task | the orchestrator creates it; the test agent works in it |
| `agents/08-implementation.md` | the ledger: every attempt, model, result | the orchestrator |

## The loop

Repeat until no task is `[ ]` other than `BLOCKED` or `HOLD` ones.

1. **Sync.** Read `tasks.md` and the tail of `progress.md`, `HUMAN NOTE:` lines first. A fresh orchestrator also reads the last ledger rows and `git log -5`.

2. **Pick.** A task is ready when it is `[ ]` without a prefix, every task in its `Depends on` is `[x]`, and the gate of the layer below it has passed. Lane rules:
    - **devops** tasks run alone: one at a time, with no other task running, because they change what everyone else builds on. A task marked `Go: required` is picked only after the user has given an explicit go for that task id, in this conversation, after seeing what it will do. Ask, then work on other ready tasks while you wait.
    - **test** tasks run any number at a time, each in its own worktree.
    - **code** tasks run any number at a time within one layer, provided no two touch the same file.

    Among ready tasks take devops first, then test, then code, each in `tasks.md` order.

3. **Brief.** Build the brief from `reference/briefs.md` for the lane. Copy entries, callee signatures, types and law sections verbatim; copy Files and Verify from the task entry. For a retry add the attempt addendum. Save it as `briefs/<id>-<attempt>.md`, then mark the task `[~]`. For a test task first prepare the worktree: `git worktree add .orchestrator/worktrees/<id> -b test/<id> scaffold`, install the dependencies there, and confirm it has no `.orchestrator/` directory and no function bodies.

4. **Spawn** a fresh agent whose only input is the brief: the harness's subagent tool, or `scripts/spawn.sh` for a headless CLI. Model class from the lane and tag (`reference/defaults.md` § Subagent models). Working directory: the main checkout, or the task's worktree for the test lane. No conversation history, no extra instructions, no other files.

5. **Check**, yourself, in this order. Do not take the agent's reply as evidence.
    1. *Scope:* `bash <skill dir>/scripts/scope_check.sh [--cwd=<worktree>] -- <Files>`. Anything outside the list is reverted (`git checkout -- <file>`, `git clean -f <file>`) and the attempt has failed, whatever else passed.
    2. *Conformance (code lane):* the signatures and doc comments of the task's entries are unchanged against the stubs.
    3. *Verify:* run the task's Verify commands and compare with the expected results.
    4. *Test review (test lane):* every new test fails against the stubs with the not-implemented error; every assertion traces to a statement in an entry, the schema or a fixture; none depends on how a function might be written; every documented behaviour and error of every entry has a test. Anything the agent reported as ambiguous is checked against the PRD: a real ambiguity is a PRD defect (`amend.md`); otherwise brief a retry with the answer, quoting the PRD.
    5. *Devops review:* each result matches the law's expected result, and a `git diff` of the configuration it wrote agrees with the sections it was given. Nothing was created that the brief did not cover.

6. **Record.** Passed: commit under the commit policy (`<id>: <title>`); for a test task commit on its `test/<id>` branch in the worktree, merge that branch into the build branch, and remove the worktree. Flip the task to `[x]`, add the ledger row, and if the agent did not append to `progress.md` write a short entry from its reply. Failed: ledger row; an `ORCHESTRATOR:` entry in `progress.md` with the failure output, so that the next attempt sees it; then the failure policy.

7. **Gate.** When the last code task of a layer passes: the whole suite so far, the conformance check over the tree, `law.sh verify`. When a component's last task passes: its fixtures end to end, its integration tests. Red means no task of the next layer starts until the failure policy has resolved it.

8. **Report** after every task and on every scheduler tick (§ Status).

## Failure policy

| Lane | Attempt 2 | Attempt 3 | Then |
|------|-----------|-----------|------|
| code | a fresh agent, same class, with the failure output (the first attempt's changes reverted) | a fresh agent, one class up | diagnose from the PRD. Wrong code: one more agent with your diagnosis in the addendum. Wrong test: a fresh test agent for that test, under test-lane rules; the code agent never touches it. Wrong or unclear PRD: `BLOCKED`, then `amend.md`. |
| test | a fresh agent, with your review findings | — | an ambiguity in the PRD: `amend.md`. Otherwise `BLOCKED`. |
| devops | a fresh strong agent with the failure output, only if nothing irreversible happened | — | stop and ask the user. Never retry a step that creates, deletes or deploys anything without their go; never weaken a check to make a pipeline pass. Do not revert devops work blindly: it may have created things outside the repository. Describe the state instead. |

Never, in any lane: edit a test so that code passes; edit code so that a test passes against the contract; loosen a verify command; mark a task done with anything red; or write the code or the test yourself. "Just this once" is how the independence that makes cheap implementation safe disappears.

**Blocking.** When a task is out of attempts: prefix its line in `tasks.md` with `BLOCKED(needs human): `, leave it `[ ]`, write a `BLOCKED` entry in `progress.md` and the ledger saying what was tried and what a human must decide, skip every task that depends on it, continue with independent work, and tell the user.

## Status

Run `bash <skill dir>/scripts/run_status.sh` and post two to four lines as visible text: per lane done, running, pending, blocked; the running task ids; the last learning; anything that needs the user (a go, a `BLOCKED`, an amendment). If nothing changed, say "still running, no change" so the user knows the loop is alive. When the loop ends, post a final summary and move to the last gate of 8.4 or to 8.5. If this conversation must end before the loop does, say so and hand the user the `run_status.sh` command.

## Steering a running build

No need to stop the loop; the next pick reads the files fresh. The user may reorder lines in `tasks.md`, prefix a task with `HOLD: ` to keep the orchestrator off it, drop a `HUMAN NOTE:` line into `progress.md`, or append a dated note to `context.md` (agents already briefed will not see it). Changing what a task says, adding one or removing one is a change to the PRD: `amend.md`.

`progress.md` is read by every code and devops agent, so keep it short: when it passes about 200 lines, condense the older entries into a "Learnings so far" section at its top, keeping every `HUMAN NOTE:` verbatim.

## Resuming

A fresh orchestrator, in a new session or after compaction:

1. `law.sh verify`.
2. Read `tasks.md`. Any `[~]` task with no agent running is abandoned: revert uncommitted changes in its files (`git status`, then `git checkout --` / `git clean -f` on those paths only), set it back to `[ ]`, and note the attempt in the ledger. Stale test worktrees: `git worktree list`, remove the ones whose task is not `[~]`.
3. Read the last ledger rows and the tail of `progress.md`, then continue the loop at step 1.

## Harness notes

- A fresh context means a new agent conversation whose first and only message is the brief. In Jetski that is `invoke_subagent` with the brief as the prompt and `Model` set per class (low `flash_lite`, mid `flash`, strong `pro`); in Claude Code a subagent with its `model` field; for any CLI, `scripts/spawn.sh --brief=<file> --class=<low|mid|strong> [--cwd=<dir>]` with `NEW_PROJECT_RUNNER_<CLASS>` set to the headless command.
- If the harness can restrict tools, a task agent needs only file editing and a shell in its working directory; nothing that reaches outside it.
- Never run two agents on the same file, and never run a devops agent alongside anything.
- A model that is not available in the class a task asks for is replaced by the next class up, never down, and the ledger records which model actually ran.

## Custom instructions

<!-- Add your own rules for the orchestrator below: concrete model names per class, how to spawn agents in your harness, status cadence, branch habits. They override the defaults above. -->
