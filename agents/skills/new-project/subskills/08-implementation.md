# Step 8 — Orchestrated Build

**Goal:** build exactly what the PRD says, cheaply, and prove it works.
**Writes:** the code and tests; `agents/08-implementation.md` (the build ledger); the git-ignored `.orchestrator/` run directory
**Runs:** always. The tier S short form is at the end.

The thinking is done. This step is a loop. An orchestrator reads the task list in the PRD and, for each task, spawns a brand-new agent with an empty context window, gives it its brief (and, for code and devops tasks, the shared context), checks the result against the PRD, records it, and moves on. The orchestrator designs nothing and writes no code. If a design question comes up, the PRD has a hole, and that goes to `amend.md`, not to improvisation.

Before starting, run `bash <this skill's directory>/scripts/law.sh verify` from the project root.

## 8.1 Lanes and visibility

What a task agent knows is decided by its lane, and these boundaries are the safety mechanism of the build. They are enforced by the brief (which is the agent's whole input), by the scope check after every task, and for the test lane physically.

| Lane | Model class | The agent gets | The agent never sees | Works in |
|------|-------------|----------------|----------------------|----------|
| code | low (`standard`) or mid (`complex`) | its brief: the entries it implements, the signatures of what it may call, the types it needs, its files, its verify commands; the shared context: `.orchestrator/context.md` and `.orchestrator/progress.md` | the PRD, other source files, tests, the ledger, this conversation | the main checkout |
| test | mid, a different model family from the code lane | its brief; the PRD bundle: `agents/prd.md` and `agents/contract/` | the shared context, any implementation, the ledger, this conversation | a git worktree of the `scaffold` tag, which holds law and stubs only |
| devops | strong | its brief, quoting verbatim the law sections it executes; the shared context | this conversation | the main checkout |

Why it is cut this way. Code agents stay cheap because they never carry more than their slice; the shared context gives them the conventions and the learnings of earlier agents without giving them the design. Test agents are the independent check on the code agents, which only works if nothing about the implementation can reach them: not the code (their worktree has none) and not the shared context (where code agents write down how they built things). Devops agents change things that are expensive or impossible to undo, so they get the strongest model and the law word for word.

## 8.2 Start the run

1. `law.sh verify`.
2. From the project root, `bash <this skill's directory>/scripts/run_init.sh`. It creates `.orchestrator/` and makes sure it is git-ignored, copies § 5 of the PRD into `.orchestrator/tasks.md` as the live checklist, writes `context.md` from `reference/context.md.tmpl`, and starts `progress.md`.
3. Fill every placeholder in `.orchestrator/context.md` from the law files: summary, layout, conventions, commands, commit policy. Keep it under about 80 lines; every code and devops agent reads it. It holds no contract entries: an agent's entries arrive in its brief.
4. Open the ledger `agents/08-implementation.md` with `Status: IN PROGRESS` as its second line (template below).
5. Run the scaffold task (D-01) through the loop. Nothing else is ready before it. Ask the user before it creates anything outside the project directory. When it is verified, commit and tag `scaffold`: test agents get their worktrees from this tag, and it contains no function bodies, which is what makes independent testing possible.
6. If the harness has a scheduler, register a status wake-up every ten minutes. Then report, and keep reporting (`orchestrator.md` § Status).

## 8.3 The loop

Read `subskills/orchestrator.md` and follow it until every task is `[x]` or `BLOCKED`. The shape of one iteration:

1. pick the ready tasks (dependencies done, layer gate passed, lane rules);
2. write each brief from `reference/briefs.md` and save it under `.orchestrator/briefs/`;
3. spawn a fresh agent per task, on the lane's model class, in the right directory;
4. check what came back yourself: scope, conformance, the task's verify commands, and for tests the review against the contract;
5. record: checklist, ledger, progress log, commit;
6. on failure apply the lane's failure policy; never fix it by hand.

The orchestrator keeps nothing in memory that is not also in a file (`tasks.md`, the ledger, `progress.md`, git), so it can be restarted fresh at any point and a long build can be handed to a new session.

## 8.4 Gates

Test at every stage, because an error left in a lower layer is inherited by everything above it.

- **After each task:** its verify commands, the scope check, and for code tasks the conformance of its signatures and doc comments with the stubs.
- **After each layer:** every test for the functions finished so far, the contract conformance check over the whole tree, and `law.sh verify`. Do not start a layer while the layer below is failing.
- **After each component is complete:** the fixtures from `agents/contract/fixtures/` for every operation that is now complete end to end, plus integration tests. The fixtures are the input and output datasets agreed in Step 2, and reproducing them is the main proof that the logic is right.
- **(L) Holdout tests** run at layer gates and in 8.5, by the orchestrator only.

Commit after each verified task, following the pull request rules in `06-deployment.md`.

## 8.5 Final testing

Test the real thing in a production-like environment, and be hard on it. This is the last gate before production. The environment and the rehearsal are devops tasks (strong model, `Go: required`); the reviews are fresh-context agents; the go is the user's.

- **Stand up staging** as `06-deployment.md` describes: the same artifact and commands as production, with realistic synthetic or anonymized data.
- **Rehearse the runbook exactly as written:** first deploy, routine deploy, rollback, restore from backup. A command that had to be changed is a defect in a law file, so raise an amendment.
- **Run everything:** the full suite including any holdout tests, the fixtures against the deployed system, end-to-end flows, migrations from empty and from a snapshot, load tests against the Step 1 targets, and all security scans.
- **Break it on purpose:** stop a service, cut off the database, fill the disk, supply bad configuration, make a dependency time out. Confirm it fails safely and that the alerts from Step 4 fire.
- **Review the whole change** against the PRD with an independent reviewer (a fresh context, ideally a different model), followed by a security review.
- **Check the logs** for secrets and personal data.
- **Ask the user for a go or no-go,** showing a readiness checklist with every item above and its result.

Then record the results in the ledger, change its status line to `Status: COMPLETE · <date>`, run `law.sh seal` to seal it, and harvest `progress.md`: anything a future build should know goes into the ledger's Learnings section and into the Custom instructions of the step that should have said it.

## Tier S short form

- **Scaffold:** a directory, the file with its stubs, a lockfile if there are dependencies, `git init`, commit, tag `scaffold`. The orchestrator may do this itself.
- **Test task:** one fresh mid-class agent writes the fixture tests from the PRD, in a worktree of `scaffold`, before any body exists.
- **Code task:** when the whole contract fits in one file of under about 150 lines, one low-class agent implements all of it as a single component-grain task. Spawning one agent per ten-line function would cost more than it saves.
- **Gates:** run the tests and every fixture in a clean environment on the machine it is meant for. Show the user the exact command to run it and the output of a real run.

## Ledger template

```markdown
# 08 — Implementation
Status: IN PROGRESS

## Environment     what the scaffold task created; the scaffold commit and tag
## Tasks           id · lane · grain · model · attempt · result · notes (one row per attempt)
## Tests           component · test agent model · tests written · reviewed against the PRD · merge commit
## Amendments      references to AMENDMENTS.md entries raised during the build, or "None"
## Final testing   the readiness checklist with results; the user's go or no-go
## Learnings       what progress.md taught that the next project should know
```

## Done when

- Every task in the PRD is `[x]` and its ledger rows are complete; nothing is `BLOCKED`.
- All tests and all fixtures pass, and the source still matches the frozen contract.
- The runbook was rehearsed without changes.
- The user has given a go.

## Custom instructions

<!-- Add your own rules for this step below: model names, how to spawn subagents, branch habits. They override the defaults above. -->
