# Subskill — Add a Feature

**Use when:** a project built with this pipeline needs new functionality after its contract was frozen.
**Produces:** `agents/features/<number>-<slug>.md`, the amended law files, the new code and tests, and a new release.

A feature is the expected, planned way for law to change. It is the same pipeline in miniature: decide everything, get the change authorized, re-freeze, then implement with cheap subagents.

If the code simply fails to do what the contract says, that is a bug, not a feature: fix the code, add a test written from the contract, and release. No law changes.

## 1. Get oriented

1. From the project root run `bash <this skill's directory>/scripts/law.sh verify`. If it fails, stop and tell the user which files changed outside the process.
2. Read every law file, `docs/ARCHITECTURE.md` and `agents/AMENDMENTS.md`.

## 2. Feature intent

Step 1 in miniature. Ask:

- What should it do, for whom, and why now?
- What does done look like? Get a concrete example.
- What is out of scope?
- Does it use any first-party tool not already listed in `01-user-intent.md`?

Size the **feature** as S, M or L, independent of the project's tier. A small feature on a large system still gets a short interview.

## 3. Walk the delta

Go through Steps 2–6 asking one question each: *what does this feature change here?* Read the matching subskill if the answer is more than "nothing".

| Area | Look for |
|------|----------|
| Inputs / outputs | New or changed operations. Is every existing caller still served? New examples. |
| Persistence | New data and new migrations (expand → migrate → contract). Never edit an old migration. |
| Security | New kinds of sensitive data, new dependencies, new entry points, new roles |
| Testing | New fixtures and tests. Which existing behaviour must provably not change? |
| Deployment | New configuration, infrastructure or runbook steps. How it is rolled out and rolled back. |

## 4. Design the contract delta

- **New functions:** full entries, as in Step 7.4. Use `decompose-function.md` where needed.
- **Changed functions:** list every caller and confirm each still fits.
- **Removed functions:** confirm nothing calls them.

Prefer adding to changing. A new function beside an old one breaks nothing; a changed signature puts every caller at risk.

Run `verify-contract.md` over the delta and everything it touches.

## 5. Write the feature spec

`agents/features/<number>-<slug>.md`:

```markdown
# Feature <number> — <name>
Status: AUTHORIZED · <date> · by <user> · contract v<old> → v<new>

## Intent             what, who, why, done, non-goals
## Law changes        per law file: section, before → after
## Contract delta     new, changed and removed schema elements and functions
## Fixtures           new examples
## Compatibility      what existing callers and data will see
## Build order        layer · function · file · tag
## Rollout, rollback  how it is released and how it is undone
## Verification       passes run, reviewer, findings
```

## 6. Get it authorized

Show the user the spec. Their explicit approval of it is the authorization to change the law, limited to exactly what the spec lists. Anything discovered later that is not in the spec goes through `amend.md`.

## 7. Apply and re-freeze

1. `law.sh unlock` the files named in the spec and apply the listed changes.
2. Add the new stubs and fixtures, and update `docs/ARCHITECTURE.md` if components changed.
3. Bump the contract version: minor for additions, major for anything that breaks an existing interface.
4. Add an entry to `agents/AMENDMENTS.md` that points to the feature spec.
5. Run `law.sh seal --amend`, commit, and tag `contract-v<new>`.

## 8. Implement

Follow `08-implementation.md` on a feature branch:

- Keep a separate ledger for this build, `agents/features/<number>-<slug>-build.md`, using the Step 8 ledger template. The original `08-implementation.md` stays sealed.
- Only new and changed functions get implementation agents.
- Independent test agents write tests for the new and changed entries, from the contract only.
- The existing test suite must pass **without being edited**. An existing test that has to change means an existing behaviour changed, and that should already be listed under Compatibility. If it is not, stop.
- Then run final testing (8.5) and release (`09-final-steps.md`).

## Custom instructions

<!-- Add your own rules for this subskill below. They override the defaults above. -->
