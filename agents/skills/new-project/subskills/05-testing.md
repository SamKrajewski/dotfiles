# Step 5 — Testing

**Goal:** decide what gets tested, how tests stay independent of the code they check, and how production is kept apart from development.
**Writes:** `agents/05-testing.md`
**Runs:** tiers M and L; tier S only if the Step 1 screening triggered it (ask only the ★ questions).

Implementation in Step 8 is done by low-power models. Tests are what make that safe, but only if they are a genuinely independent check. A test written by an agent that has read the implementation tends to confirm what the code does instead of what the contract says.

## Questions

- ★ What must never break? Tests concentrate there.
- ★ Is reproducing the Step 2 examples enough proof that it works, or is more needed?
- Which kinds of tests does this project need? (Propose from the table below.)
- What may tests touch? For each first-party tool in Step 1: the real thing, a sandbox, or a fake?
- Are there performance or load targets to prove?
- When do tests run: locally, before commit, in CI, nightly?
- Which environments exist, and how are they kept apart?

## Kinds of tests

| Kind | Proves | S | M | L |
|------|--------|---|---|---|
| Fixture tests: the Step 2 examples, end to end | Output matches the agreed examples | ✔ | ✔ | ✔ |
| Static checks: format, lint, types | No class of trivial error | ✔ | ✔ | ✔ |
| Unit tests, per contract function | Each function meets its entry | key functions | ✔ | ✔ |
| Property-based tests | Invariants hold on generated input | – | parsers, maths | ✔ |
| Integration tests against real stores (containers) | Components work together | – | ✔ | ✔ |
| Schema conformance (for example Schemathesis) | The API matches its schema | – | if an API | ✔ |
| Migration tests | Schema changes apply from empty and from a snapshot | – | if a database | ✔ |
| End-to-end | Whole user flows on a deployed stack | – | smoke only | ✔ |
| Security tests | Role × operation table enforced; injection; fuzzing | – | basic | ✔ |
| Load tests | Step 1 targets are met | – | if targets exist | ✔ |

Suggested bar: every behaviour and every error documented in a contract entry has at least one test. Treat coverage percentages as a signal, not a goal.

## Independence

These rules become law for Step 8. Record any changes the user wants.

- **Tests come from the PRD only.** Test-writing agents receive their brief and the PRD bundle: `agents/prd.md` and `agents/contract/` (schema, stubs, fixtures). They never see implementation code, the shared context that implementation agents read and write (`.orchestrator/`), the build ledger, or the conversation.
- **Make that physical, not a promise.** Each test agent works in a git worktree of the `scaffold` tag (stubs only, no function bodies, no `.orchestrator/` directory), so there is nothing to read.
- **Separate agents, fresh context.** Every test agent is a new agent whose only input is its brief. It has never been an implementation agent for the same code, and the reverse. Use a different model family for tests than for implementation, so they do not share blind spots.
- **Implementers can run tests but not edit them.** Test agents cannot edit source. The orchestrator's scope check enforces both after every task.
- **The contract arbitrates.** When a test fails, the orchestrator decides which side departs from the contract, and a fresh agent of that role fixes it. Neither side adjusts to match the other. If the contract is ambiguous, that is a contract defect: `amend.md`.
- **Never weaken a test to make it pass, and never special-case code to satisfy a test.**
- **Tests must fail against the stubs.** A test that passes before the function is implemented tests nothing.
- **Fake only declared boundaries:** the outside systems listed in Step 1. Never fake the thing under test.
- (L) **Hold some tests back.** Keep a set that implementation agents never see and only the orchestrator runs, to catch code that fits the visible tests instead of the contract.

## Separating production from development

- Name the environments: local, test/CI, staging (optional for M, required for L), production.
- Each has its own configuration, credentials, databases and storage. Configuration comes from the environment, never from code.
- Production credentials do not exist on development machines or in any agent's context.
- Test data is synthetic. If a production-like snapshot is needed, it is anonymized first.
- Anything destructive in test tooling refuses to run unless the environment is explicitly a test one (for example, the database name must end in `_test`).
- Production changes only through the deployment process in Step 6.

## Output template

```markdown
# 05 — Testing
Status: APPROVED · <date> · approved by <user>

## Critical behaviour   what must never break
## Test plan            each kind of test: scope, tool, when it runs
## Coverage bar         what "tested enough" means here
## Test doubles         each outside system: real, sandbox or fake
## Independence rules   the rules above, with any changes
## Environments         each environment: purpose, data, credentials, who may deploy
## Performance targets  figures to prove, or "None"
```

## Done when

- Each kind of test in the plan has a scope, a tool and a trigger.
- The independence rules are accepted or explicitly adjusted by the user.
- Every environment is named, with its data and credentials kept separate.
- The user has approved it.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
