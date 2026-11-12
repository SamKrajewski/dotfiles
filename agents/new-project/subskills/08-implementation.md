# Step 8 — Implementation

**Goal:** build exactly what the contract says, cheaply, and prove it works.
**Writes:** the code and tests; `agents/08-implementation.md` (the build ledger)
**Runs:** always. The tier S short form is at the end.

The thinking is done. This step is execution: the orchestrator hands out small jobs, checks results against the contract, and keeps the ledger. It designs nothing. If a design question comes up, the contract has a hole, and that goes to `amend.md`, not to improvisation.

Before starting, run `bash <this skill's directory>/scripts/law.sh verify` from the project root.

## 8.1 Development environment

Build what Steps 3–6 decided. Nothing here should need a new decision.

- **Repository:** create the git repositories. The first commit is the law files, tagged `contract-v1.0.0`. Set up the remote, branch protection and `CODEOWNERS` from `06-deployment.md`.
- **Permissions and ownership:** who and which agents may write where. Law files are owned by the user. If the agent harness supports path-level write rules, deny writes to the sealed files (in Claude Code, `permissions.deny` in `.claude/settings.json`).
- **File structure:** as in `docs/ARCHITECTURE.md`. Copy the stubs from `agents/contract/stubs/` into the source tree.
- **Dependencies:** set up the build system and install exactly the pinned list from `04-security.md`. Commit the lockfile.
- **Containers and services:** container files, the local compose setup, test databases, with migration 0001 applied.
- **Configuration:** config files and a `.env.example`. No real secrets in the repository.
- **Checks:** pre-commit hooks and the CI pipeline: format, lint, types, tests, security scans, the manifest check, and a contract conformance check that compares the signatures and doc comments in the source with the frozen stubs.

Ask the user before creating anything outside the project directory: remote repositories, cloud resources, anything that costs money or is visible to others.

Finish by proving the scaffold: from a clean checkout, one command builds, the stubs compile, the test runner starts, and CI passes. Commit and tag this `scaffold`. It contains no function bodies, which is what makes independent testing possible.

## 8.2 Subagent swarm

One subagent per function in the contract, in the order given by the Build order table in `07-contract.md`.

| Tag | Model class | Examples |
|-----|-------------|----------|
| `standard` | Low-power | Haiku, Gemini 3.0 Flash |
| `complex` | Mid-low | Sonnet, Gemini 3.8 Flash |

Keeping implementation on cheap models is what the planning paid for. If a function seems to need a stronger model, the entry is under-specified: fix the plan, do not raise the model.

**Order.** Work layer by layer, lowest first. Functions within a layer can run in parallel, except that two agents must never edit the same file at once: run those one after another.

**The brief.** A subagent knows nothing about this conversation, so its brief must be complete, and it should contain only its own slice of the contract. That saves tokens and removes the temptation to wander.

```
Implement exactly one function.

Function: <name>, in <file>
Contract entry: <signature and full doc comment>
Functions you may call (signatures and one-line purpose): <…>
Types you need: <…>
Conventions: <error-handling pattern, style rules, format and lint command>

Rules:
- Replace only the body of <name>. Do not change its signature or doc comment.
- Do not touch any other function or file. Do not add dependencies.
- Everything you need is in this brief. Do not edit anything under agents/,
  and do not edit any test.
- You may run this function's tests with <command> if they exist. Make the
  code satisfy the contract entry; never special-case it to satisfy a test.
- If the entry is ambiguous, contradictory or impossible, or a test seems to
  contradict it, stop and report what you found. Do not guess and do not
  work around it.
- Finish by running <format, lint and type-check command> on the file.

Reply with "done", or "blocked: <reason>".
```

**When a function fails its checks:**

1. Retry once at the same model class, with the failure output.
2. Escalate one class, with a fresh agent.
3. The orchestrator diagnoses. Wrong code: brief a new agent. Wrong test: back to a test agent (8.4). Wrong or unclear contract: stop that function and follow `amend.md`.

**The ledger.** Record every function in `agents/08-implementation.md`: function, file, tag, model, attempts, status, notes. Only the orchestrator writes this file. Keep its second line as `Status: IN PROGRESS` during the build: that is what tells `law.sh` to leave it writable.

## 8.3 Continuous testing

Test at every stage, because an error left in a lower layer is inherited by everything above it.

- **After each function:** format, lint, type check, and its unit tests if they exist yet.
- **After each layer:** every test for the functions finished so far, the contract conformance check, and `law.sh verify`.
- **After each component:** the fixtures from `agents/contract/fixtures/` for every operation that is now complete end to end, plus integration tests. The fixtures are the input and output datasets agreed in Step 2, and reproducing them is the main proof that the logic is right.

Do not start a layer while the layer below is failing. Commit in small pieces, following the pull request rules in `06-deployment.md`.

## 8.4 Independent tests

Tests are written from the contract alone, by subagents that cannot see the implementation. This is the most important rule in this step: tests written with sight of the code check what the code does, not what it should do. The rules agreed in `05-testing.md` apply.

- **Start them alongside 8.2, or before it.** Test authors need only the contract, so nothing blocks them, and 8.3 then has tests to run.
- **Isolate them physically.** Each test agent works in a separate checkout of the `scaffold` tag (a git worktree, for example), where no function body exists.
- **Brief them** with the contract entries for their component, the schema, the fixtures and the test plan from `05-testing.md`. Ask for a test per documented behaviour and per documented error. Use the mid-low model class.
- **Check the tests against the contract** before trusting them: each asserts behaviour that an entry states, none depends on how a function is written inside, and all of them fail against the stubs.
- **Bring them into the main branch read-only** for implementers. Implementers may run tests. They may not edit them.
- **Disputes go to the contract.** The orchestrator decides which side departs from it, and a fresh agent of that role makes the fix.
- (L) Keep the held-back test set away from implementation agents entirely.

## 8.5 Final testing

Test the real thing in a production-like environment, and be hard on it. This is the last gate before production.

- **Stand up staging** as `06-deployment.md` describes: the same artifact and commands as production, with realistic synthetic or anonymized data.
- **Rehearse the runbook exactly as written:** first deploy, routine deploy, rollback, restore from backup. A command that had to be changed is a defect in a law file, so raise an amendment.
- **Run everything:** the full suite including any held-back tests, the fixtures against the deployed system, end-to-end flows, migrations from empty and from a snapshot, load tests against the Step 1 targets, and all security scans.
- **Break it on purpose:** stop a service, cut off the database, fill the disk, supply bad configuration, make a dependency time out. Confirm it fails safely and that the alerts from Step 4 fire.
- **Review the whole change** against the contract with an independent reviewer (a fresh context, ideally a different model), followed by a security review.
- **Check the logs** for secrets and personal data.
- **Ask the user for a go or no-go,** showing a readiness checklist with every item above and its result.

Then record the results in the ledger, change its status line to `Status: COMPLETE · <date>`, and run `law.sh seal` to seal it.

## Tier S short form

- **8.1:** a directory, the file, a lockfile if there are dependencies, `git init`.
- **8.2:** when the whole contract fits in one file of under about 150 lines, a single low-power subagent may implement all of it. Spawning one agent per ten-line function would cost more than it saves.
- **8.4:** one separate subagent writes fixture tests from the contract, without seeing the code.
- **8.3 / 8.5:** run the tests and every fixture in a clean environment on the machine it is meant for. Show the user the exact command to run it and the output of a real run.

## Ledger template

```markdown
# 08 — Implementation
Status: IN PROGRESS

## Environment     what 8.1 created, and the scaffold commit
## Functions       function · file · tag · model · attempts · status · notes
## Tests           component · test agent model · count · reviewed against contract
## Amendments      references to AMENDMENTS.md entries raised during the build, or "None"
## Final testing   the readiness checklist with results; the user's go or no-go
```

## Done when

- Every function in the contract is implemented and its ledger row is complete.
- All tests and all fixtures pass, and the source still matches the frozen contract.
- The runbook was rehearsed without changes.
- The user has given a go.

## Custom instructions

<!-- Add your own rules for this step below: model names, how to spawn subagents, branch habits. They override the defaults above. -->
