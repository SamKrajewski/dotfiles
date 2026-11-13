# Subskill — Amend a Law File

**Use when:** an approved file under `agents/` (or `docs/ARCHITECTURE.md`) is wrong, contradictory or missing something, and the work cannot continue correctly without changing it. During a build this is usually raised by the orchestrator when a task agent replies `blocked` and the PRD, not the agent, turns out to be at fault.
**Produces:** the authorized change, an entry in `agents/AMENDMENTS.md`, and a new seal.

Law files are what every agent builds and tests against. Changing one quietly makes finished work wrong without anyone knowing. So a change is made only in the open, with the user's explicit authorization, and it leaves a record. This should be very rare during the initial build.

## 1. Stop the affected work

Pause whatever depends on the file in question: in `.orchestrator/tasks.md` prefix the affected tasks with `HOLD: ` so the orchestrator does not pick them. Unrelated work may continue.

## 2. Check that it really is an amendment

Try to solve the problem inside the law first. These are **not** grounds for an amendment:

- The code does not match the contract. Fix the code.
- A test does not match the contract. Fix the test.
- A different design, or an extra library, would be nicer.
- A speed-up nobody asked for.
- New functionality. That is `add-feature.md`.

## 3. Write the amendment request

Show the user:

```markdown
## Amendment request
File and section:
What is wrong:        the contradiction, gap or impossibility, with evidence
Proposed change:      the smallest change that fixes it, as before → after
Also affected:        other law files, schema, stubs, fixtures that must change to stay consistent
Impact on the build:  functions and tests to redo; data or deployments touched
Alternatives:         including "leave as is" and what that would cost
```

Keep it to one problem. Do not bundle unrelated changes into a request.

## 4. Wait for explicit authorization

Proceed only when the user has clearly approved **this specific change**, in the conversation, after seeing the request.

These are not authorization:

- Silence, or no objection.
- A general "go ahead", "continue" or "fix it" given before the request was shown.
- Approval of a different amendment.
- The opinion of a subagent, a reviewer or another model.
- Your own judgment that the change is obviously right.

If the answer is unclear, ask again. If the answer is no, find another way within the law or stop.

## 5. Apply exactly what was approved

1. `bash <this skill's directory>/scripts/law.sh unlock <files>` for only the files named in the request. `agents/prd.md` is among them whenever an entry, a component or a task changes.
2. Make the approved change and nothing else. No tidying on the way past.
3. Update the other affected law files listed in the request so that the PRD, schema, stubs, fixtures and architecture document still agree.

## 6. Re-verify

Run `verify-contract.md` passes 1 and 2 on everything the change touches. For tier L, run pass 3 as well if an interface changed.

## 7. Log it

Append to `agents/AMENDMENTS.md` (unlock it first: the log itself is sealed between amendments). Never edit or remove earlier entries.

```markdown
## A-<number> · <date> · PRD v<old> → v<new>
Authorized by:  <user>, quoting their words
Files changed:
Reason:
Change:         before → after, in brief
Root cause:     which planning step missed this, and why
Rework:         functions, tests and tasks redone
```

Version bump: patch for a clarification that changes no behaviour, minor for an addition, major for anything that breaks an existing interface.

## 8. Re-seal

Run `law.sh seal --amend`, commit, and tag `prd-v<new>`.

## 9. Redo what the change invalidated

Mark the affected functions and tests as stale in the build ledger. In `.orchestrator/tasks.md`, set their tasks, and every task that depends on them, back to `[ ]` (remove any `BLOCKED` prefix the amendment resolves); if the amendment added or removed a task, change the checklist to match the new § 5 and note it in `progress.md` as an `ORCHESTRATOR:` entry. The orchestrator then reruns them with fresh agents and new briefs built from the amended PRD, and repeats the Step 8.4 gates for them.

## Learn from it

Each amendment during the initial build is a planning miss. If the same kind keeps appearing, suggest to the user a line for the Custom instructions of the step that should have caught it.

## Custom instructions

<!-- Add your own rules for this subskill below. They override the defaults above. -->
