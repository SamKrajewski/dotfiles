# Briefs

A brief is the one message a task agent receives. The agent's context is empty, so the brief is its entire world: it must be complete, and it must contain only the agent's own slice. The orchestrator fills a template below from the PRD, the stubs and the task entry, saves it as `.orchestrator/briefs/<id>-<attempt>.md`, and sends it verbatim as the agent's first and only instruction.

Rules for every brief:

- **Copy, never paraphrase.** Entries, signatures, types and law sections go in word for word from the stubs, the PRD and the law files.
- **Only this task's slice.** A code brief carries no PRD, no entries beyond its own plus the signatures it may call, no files beyond its own.
- **Say what the agent may not do** as plainly as what it must do.
- **Nothing from the conversation:** no history, no "as we discussed", no secrets, no opinions about how to do it.
- **End with the reply format.** The orchestrator reads the first line of the reply.

Placeholders are in `<angle brackets>`; remove every one.

## Code task, function grain

```
You are implementing one task of a frozen contract. Your context is fresh on purpose: this brief and the two shared context files named below are everything you may use. Do not look for more.

TASK <id>: implement `<function>` in `<file>`

CONTRACT ENTRY (the signature and doc comment are law; do not change them):
<signature and full doc comment, verbatim from the stub>

YOU MAY CALL (these exist; beyond them use only the standard library and the project's declared dependencies):
<for each: signature · one-line purpose · file>

TYPES YOU NEED:
<definitions, verbatim>

FILES YOU MAY EDIT: `<file>`, and in it only the body of `<function>`.

SHARED CONTEXT: read `.orchestrator/context.md` (conventions, layout, commands, rules) and `.orchestrator/progress.md` (learnings from earlier tasks; lines starting `HUMAN NOTE:` override everything else there). When you finish, append your entry to `progress.md` in the format `context.md` shows.

VERIFY (run before you reply; all must pass):
<verify commands from the task entry>
Tests for this function already exist. You may run them and read their output. You may not edit them. Make the code satisfy the contract entry; never special-case it to satisfy a test. If a test contradicts the entry, stop and report which one and how.

RULES:
- Replace only the body of `<function>`. Touch no other function, no other file. Add no dependency.
- Do not open `agents/`, `tests/`, or any source file other than the one you edit. The signatures above are all you may rely on; if they are not enough, the task is under-specified: reply blocked.
- If the entry is ambiguous, contradictory or impossible, stop. Do not guess, do not work around it.
- Finish with the format, lint and type-check commands from `context.md` on your file.
- Do not commit.

REPLY with exactly one of:
done — <each verify command and its result> — learnings: <one line, or "none">
blocked: <what is missing or contradictory, quoting the entry>
```

## Code task, component grain

The function-grain brief with these parts changed:

```
TASK <id>: implement component `<component>`: <n> functions in <files>, in this order:
  1. `<function>` in `<file>`
  2. …

CONTRACT ENTRIES (each signature and doc comment is law; do not change them):
<every entry, verbatim, in the order above>

YOU MAY CALL (outside this component):
<for each: signature · one-line purpose · file>

FILES YOU MAY EDIT: <files>, and in them only the bodies of the functions listed above.

RULES (in addition):
- Implement in the order given: each function calls only functions listed before it or under YOU MAY CALL.
- Run the component's verify commands once every body is in; fix only what is yours.
```

## Test task

```
You are writing the tests for one component of a frozen PRD. You work in a checkout that holds the PRD and interface stubs only: there is no implementation anywhere in it, and no notes from other agents. That is deliberate. The PRD is your only source, and tests written from it alone are what makes cheap implementation safe.

TASK <id>: tests for component `<component>`
WORK IN: `<worktree path>` (a checkout of the `scaffold` tag). Do not leave it.

READ:
- `agents/prd.md`: § 1 Idea, § 2 Testing, § 3 the `<component>` entry, § 4 Contract
- `agents/contract/stubs/<paths>`: the entries you are testing, listed below
- `agents/contract/schema/<paths>`
- `agents/contract/fixtures/<operation>/` for each operation listed below

ENTRIES: <function · file, one per line>
FIXTURES: <operation/case, one per line>
KINDS OF TESTS for this component (from the test plan): <unit tests per entry; fixture tests per case; property-based tests for …; …>
TEST DOUBLES: fake only these declared boundaries: <list from 05-testing.md>. Never fake the thing under test.
WRITE TO: `<tests/path>` only.
RUN WITH: `<command>`

RULES:
- One test per documented behaviour and one per documented error of every entry, and one per fixture case. Name each test after the behaviour it checks.
- Assert only what an entry, the schema or a fixture states. Where the contract leaves something open, do not choose a reading: list it under "ambiguous" in your reply instead of writing the test.
- Every test must fail against the stubs. Run the suite and confirm that every test fails with the not-implemented error, not with an import, collection or syntax error.
- Do not edit anything outside `<tests/path>`. Do not edit `agents/`. Do not create or look for any other file.
- Do not commit.

REPLY with exactly one of:
done — <n> tests in <files> — all fail against the stubs: yes — ambiguous: <list, or "none">
blocked: <reason>
```

## Devops task

```
You are carrying out one infrastructure task for a project whose decisions are frozen in law files. This lane is mission critical: a wrong CI gate lets bad code through, a wrong deploy step costs money or cannot be undone. Follow the law exactly; do not improve it.

TASK <id>: <title>

LAW TO EXECUTE (verbatim; these sections are the specification):
<the named sections of 03/04/05/06, quoted in full>

FILES YOU MAY CREATE OR EDIT: <list>

SHARED CONTEXT: read `.orchestrator/context.md` and `.orchestrator/progress.md` first (`HUMAN NOTE:` lines override). Append your entry to `progress.md` when you finish.

VERIFY (each command with its expected result):
<command → expected result>

GO: <"not required" | "the user authorized on <date>: '<their words>', covering exactly: <what>">

GUARDRAILS:
- Create nothing outside the project directory, and nothing that costs money or is visible to others (remote repositories, cloud resources, DNS, secret stores, branch rules, deployments) unless GO above covers it exactly.
- Never run a destructive command (delete, drop, truncate, force-push, remove a data directory, tear down a resource) unless this brief names that exact command.
- No secret in any file. Secrets come from the environment or the secret manager the law names.
- Pin what the law says to pin: actions, images and tools by digest or exact version.
- If a command in the law fails or is wrong, stop and report it exactly as it happened. Do not substitute, do not work around, do not weaken a check.
- Do not commit.

REPLY with exactly one of:
done — for each verify command: command, expected, actual — created outside the repository: <list, or "nothing"> — learnings: <one line, or "none">
blocked: <what failed, the verbatim output, and what the user must decide>
```

## Retry addendum

Appended to the brief of attempt 2 and later:

```
PREVIOUS ATTEMPT <n> FAILED. Another agent tried this task and the orchestrator rejected the result. <Code and test lanes: "Its changes were reverted; you start from the original files." Devops lane: "Its changes are still in place; the state is described below.">

What went wrong:
<verify output, scope violations, review findings or the orchestrator's diagnosis, verbatim>

Do not repeat it. If you believe the failure comes from the contract entry or the law rather than from the work, reply blocked and say why.
```

## Custom instructions

<!-- Add your own brief rules below: house phrasing, extra guardrails, a harness-specific preamble. They override the defaults above. -->
