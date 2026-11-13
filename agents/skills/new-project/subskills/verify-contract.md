# Subskill — Verify the Contract

**Use when:** Step 7.8, before the freeze; and again on the affected part after any amendment or feature.
**Produces:** § 6 of `agents/prd.md`: the "Verification record" and "Safety review".

The PRD is about to be implemented by models that will not question it, tested by models that see nothing else, and run as a task list by an orchestrator that may not improvise. Every function has to fit every other function and every task has to be completable from its brief, and it is far cheaper to prove that on paper than to discover it halfway through the build. Give this real time.

| Tier | Passes to run |
|------|---------------|
| S | 1 and 2, done by you; then the user reads the PRD |
| M | 1, 2 and 3; pass 4 if there is sensitive data or a destructive operation |
| L | All four |

## Pass 1 — Mechanical

Let tools find what tools can find:

- The stubs compile or type-check at the strictest settings.
- The schema passes its linter.
- Every fixture validates against the schema.
- The contract documentation builds to HTML without warnings.
- The component and function dependency graphs have no cycles.

## Pass 2 — Trace

Walk the contract yourself, deliberately:

- **Requirements → functions.** Every success criterion, operation and decision in law files 01–06 maps to the functions that deliver it. Record this as the Traceability table. A requirement with no function is a hole.
- **Entry points → leaves.** For each operation in the schema, follow the calls down. At every call check that the arguments match the callee's signature in type, order, units and nullability; that the caller uses the return value as the callee documents it; and that each error the callee can raise is either handled or declared by the caller.
- **Fixtures by hand.** Take at least one fixture per operation and step it through the call chain. Can these functions, exactly as specified, turn that input into that output? This catches missing functions and missing data better than anything else.
- **Orphans.** A function nobody calls, a field nobody reads, or an error nobody raises is either dead weight or a sign that something else is missing.
- **Effects.** Where several writes belong together, some function owns the transaction. Anything that can be retried is safe to repeat.
- **Tasks → coverage.** Every function is in exactly one code task; every component has a test task; every decision in 03–06 has a devops task or a `manual (user)` note; every `Depends on` names a task that exists and comes earlier; no two tasks list the same file; every Verify is a runnable command with an expected result; every task that reaches outside the project directory is marked `Go: required`.
- **Briefs by hand.** Take one code task and one devops task and write their briefs from `reference/briefs.md`. If the brief needs anything that is not in the PRD or the law files, the PRD is incomplete.

## Pass 3 — Independent review

Whoever wrote the contract shares its blind spots, so the reviewer must come to it cold.

- **Preferred: a model from a different vendor** than the author (GPT or Gemini if Claude wrote it, and the reverse), through whatever CLI or API the user has set up. Different architectures make different mistakes.
- **Fallback:** a fresh-context subagent on the strongest available model, or the user reading the generated HTML.
- **Ask first.** Sending the contract to another vendor shares the project's design with a third party. Get the user's consent before the first such call, and never include secrets.

Give the reviewer only the PRD and the law files, never the conversation. A prompt to start from:

```
You are reviewing a software PRD before it is frozen. Its contract will be
implemented by low-capability models that follow it literally and cannot ask
questions, its tests will be written by models that see nothing but this PRD,
and its task list will be run by an orchestrator that may not improvise. Your
job is to find defects, not to confirm that it is good.

Read the attached documents and report every case where:
1. A call does not match the callee's signature (types, order, units, nullability).
2. A function's entry is ambiguous enough that two reasonable implementers
   would write different behaviour.
3. An error can occur but is neither handled nor declared.
4. A requirement or schema operation has no function that delivers it.
5. A fixture cannot be produced by the functions as specified.
6. Two documents contradict each other.
7. A task could not be completed by an agent that sees only its brief: a
   missing callee, missing verification, a decision left to the implementer,
   or a devops task that would have to improvise a command.

For each finding give: the location, what is wrong, why it matters, and the
smallest fix. Mark each "blocking" or "minor". If you find nothing in a
category, say so.
```

Fix every blocking finding in the PRD, rerun passes 1 and 2 on what changed, and review again. Stop when a pass returns nothing blocking. A fix that would change an approved file from Steps 1–6 needs the user's authorization.

## Pass 4 — Safety review

Read the PRD against `03-persistence.md` and `04-security.md`, as someone trying to make it cause harm:

- **Every function with side effects:** what is the worst it can do with bad input or a bug? Is each destructive operation guarded the way Step 3 says?
- **Every entry point:** is authorization checked on every path before anything is read or written?
- **Every sensitive field:** follow it through the functions. Does it reach a log, an error message, a response or a third party that it should not?
- **Every trust boundary:** is input validated where it enters, before use?
- **Failure halfway:** if a function stops between two writes, what state is left? Are retries safe?
- **Exhaustion:** can a caller make it consume unbounded memory, storage, time or money?
- **Migrations:** does each follow the expand → migrate → contract rule?

Record each finding and its resolution in the Safety review section.

## The verification record

```markdown
| Pass | Run by (model) | Date | Blocking | Minor | Outcome |
|------|----------------|------|----------|-------|---------|
```

List each blocking finding with its fix beneath the table. An honest record with findings is worth more than an empty one.

## Custom instructions

<!-- Add your own rules for this subskill below: preferred review model, how to call it, extra checks. They override the defaults above. -->
