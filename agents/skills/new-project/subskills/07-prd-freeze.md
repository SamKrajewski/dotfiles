# Step 7 — PRD Freeze

**Goal:** turn the earlier decisions into one exact, verified PRD — the idea, the logical components, the contract for every function, and the task list that builds it — and seal it.
**Writes:** `agents/prd.md`, `agents/contract/`, `docs/ARCHITECTURE.md`, `agents/MANIFEST.sha256`
**Runs:** always. Tier S writes everything into `agents/prd.md` and skips 7.5.

This is the last point where changing your mind is cheap. After the freeze the PRD is all the build sees: fresh-context agents implement its entries literally, test agents write tests from it and nothing else, and the orchestrator hands out its tasks without designing anything. Anything vague becomes a wrong guess and anything missing becomes an amendment, so take the time. This step is allowed to be slow.

The PRD has four layers. Each refines the one above it, and a task may be cut at either of the last two.

| Layer | Answers | Built in |
|-------|---------|----------|
| **Idea** | what is wanted, for whom, why, and what "done" means | Step 1, copied here |
| **Logical components** | which pieces exist, what each owns, how they depend on each other, and at what grain each is built | 7.3 |
| **Contract** | every type and every function, exactly | 7.2, 7.4, 7.5 |
| **Tasks** | who builds what, in which lane, in what order, verified by which command | 7.6 |

**The test for every entry:** could a model that has never seen this conversation implement it correctly from the entry alone, plus the signatures of what it calls? If not, the entry is not finished. **The test for the whole PRD:** could a test agent given only `agents/prd.md` and `agents/contract/` write every test, and could an orchestrator given only the PRD and the law files run the whole build without asking a question?

The PRD refines the earlier law files and must never contradict them. If it has to, the earlier file is amended first.

## 7.1 Reconcile

Reread every law file. List each contradiction, gap and leftover vagueness, and resolve them with the user now. A fix that changes an approved file needs their authorization (`amend.md`). No open question survives this sub-step.

## 7.2 Schema

Harden Step 2 into a machine-readable schema under `agents/contract/schema/`: OpenAPI, JSON Schema, Protocol Buffers, AsyncAPI, or for a CLI a structured file listing each command, flag, type and exit code. Whatever the interface, it must end up represented as data.

- Every field has a type, required or optional, nullability, format, limits and default.
- Every operation has its input, its success output and each error output.
- Persisted data is included: the initial migration from Step 3.
- Lint the schema with a real tool (Spectral, `buf lint`, a JSON Schema validator).

Turn the Step 2 examples into fixture files: `agents/contract/fixtures/<operation>/<case>.input.*` and `<case>.expected.*`. Validate every fixture against the schema. A fixture that does not validate means the schema or the example is wrong, and it is better to learn which now.

## 7.3 Components

Break the problem into digestible pieces, by logical component. Every major service, complex task and reusable feature is a component. For each one:

- **Purpose** in one sentence. If it needs "and", consider splitting it.
- **Owns:** the data and responsibilities that belong to it alone.
- **Interface:** what other components may call.
- **Depends on:** which components it may call. Dependencies must not form a cycle.
- **Files:** where it lives. Two components never share a file.
- **Grain:** whether Step 8 builds it as one task or as one task per function (below). Decide provisionally now and confirm after 7.4, when the tags are known.

**Grain.** A task is what one fresh-context agent completes and the orchestrator verifies, so the grain decides how much contract one agent carries. Build a component as **one component-grain task** when all of these hold:

- Its functions are all `standard`, or at most one is `complex` and that one is the component's own orchestrating function.
- Its contract fits in one brief: about eight functions or fewer, roughly 200 lines of stubs, in one or two files.
- Its tests and fixtures can verify it as a whole.

Otherwise build it at **function grain**: one task per function, in layer order. That is the right choice for components with several `complex` functions, components that many others call into, and anything touching persistence, authentication or money. A component may be **mixed**: its `complex` functions as function-grain tasks, the remaining helpers as one component-grain task. Tier S is usually one component at component grain; tier L is mostly function grain. Record the grain and the reason in the component's entry.

For any project with more than one file, write `docs/ARCHITECTURE.md`. It is for humans: simple, high level, readable in five minutes, about 150 lines at most. What the system is, one diagram (Mermaid or ASCII), a table of components, the flow of one or two main operations, a directory map, and pointers to the law files for detail. No function-level content.

## 7.4 Functions

Write the signature and contract entry for **every** function: public operations, handlers, helpers that carry logic, database queries, entry points. Shared types, enums, error types, constants and configuration keys are part of the contract too.

Each entry states:

| Field | Content |
|-------|---------|
| Signature | Name, parameters and return, fully typed |
| Purpose | One sentence |
| Params | Meaning, valid range and units of each |
| Returns | Meaning, shape, ordering guarantees |
| Errors | Each failure condition → the error raised or returned |
| Effects | "Pure", or every read, write, network call and mutation |
| Requires / Ensures | What the caller guarantees; what holds afterwards |
| Calls | The contract functions it uses, in order where order matters |
| Example | At least one input → output, and one failure |
| Tag | `standard` or `complex` |

In a doc-comment format it looks like this:

```python
def parse_duration(text: str) -> timedelta:
    """Convert a human duration such as "1h30m" into a timedelta.

    Args:
        text: One or more <integer><unit> pairs. Units are h, m or s,
            largest first, each at most once, no spaces. 1–32 characters.
    Returns:
        The total duration. Always greater than zero.
    Raises:
        DurationFormatError: text is empty, too long, has an unknown unit,
            repeats a unit, is out of order, or totals zero.
    Effects: pure.
    Calls: none.
    Example:
        parse_duration("1h30m") == timedelta(minutes=90)
        parse_duration("30m1h") raises DurationFormatError
    Tag: standard
    """
    raise NotImplementedError
```

**Tagging.** The tag picks the model class that implements the function in Step 8. Tag a function `complex` if, after decomposition, it still coordinates several calls with error handling between them; involves concurrency, transactions or retries; implements a non-trivial algorithm; or is security-critical (authentication, permission checks, sanitizing input). Everything else is `standard`.

**Decomposing.** If a function cannot be described in about 15 lines, has more than one kind of side effect, or mixes decisions with input/output, run `decompose-function.md` on it. A generic endpoint handler is the typical case. If more than about a fifth of the functions end up `complex`, decompose further: the plan is carrying too little of the difficulty.

**Layers.** Sort the functions into layers. Layer 0 calls no other contract function; layer N calls only layers below it. Record the layer with each function; 7.6 orders the tasks by it.

## 7.5 Contract format (tiers M and L)

Save the contract as real, compilable interface stubs with doc comments, in the language's standard documentation format: Javadoc, Python docstrings, TSDoc, rustdoc, Go doc comments, Doxygen. Put them in `agents/contract/stubs/`, mirroring the source tree, with every body replaced by a "not implemented" error.

- The stubs must compile or type-check. That proves the types line up before any body exists.
- Generate HTML from them (`reference/defaults.md` § Libraries, "Contract docs to HTML") into `docs/contract/` so the user can browse the contract. The HTML is a build product and is not sealed.

Tier S: the entries live as a section of `agents/prd.md`. No stubs, no HTML.

## 7.6 Tasks

Turn the contract and the law files into the work order for Step 8. A task is the unit one fresh-context agent completes from its brief alone and the orchestrator verifies with commands, so every task must be finishable without a decision and checkable without a judgment call. Tasks fall into three lanes, and the lane decides the model class and what the agent is allowed to see:

| Lane | Builds | Drawn from | Model class |
|------|--------|------------|-------------|
| `devops` | the environment and everything that ships or protects the code: repository, CI/CD, containers, data stores and migrations, environments, deploys, monitoring | Steps 3, 4, 5 (environments) and 6 | strong. Mission critical: a wrong CI gate lets bad code through; a wrong deploy step costs money or cannot be undone |
| `test` | the tests, from the PRD alone | Step 5 and the contract | mid, a different model family from the code lane |
| `code` | the contract bodies, at the grain decided in 7.3 | the contract | by tag: `standard` low, `complex` mid |

**Devops tasks.** Walk law files 03–06 and turn every decision into a task that executes it. The usual sequence, trimmed by tier:

| Task | Does | Law |
|------|------|-----|
| scaffold (always first) | repository and first commit (the law files, tagged `prd-v1.0.0`); directory structure from `docs/ARCHITECTURE.md`; stubs copied into the source tree; the pinned dependencies installed and the lockfile committed; configuration and `.env.example`; pre-commit hooks; `.orchestrator/` git-ignored. Proves itself: a clean checkout builds, the stubs compile, the test runner starts. Tagged `scaffold`. | 04 § Stack, 06 § Build |
| checks | the CI pipeline with every per-pull-request check in 06, including the manifest check and a contract conformance check (signatures and doc comments in the source match the frozen stubs) | 06 § CI/CD, 04 § Ongoing verification |
| data | local services and test databases; migration 0001 applied from empty; backup job and restore test | 03 |
| access | remote repository, branch protection, `CODEOWNERS`, review rules | 06 § Version control |
| security | scanners on a schedule, secret scanning, automated dependency updates, (L) SBOM | 04 |
| environments | staging; secrets injection; monitoring and alerts to a named person | 04 § Monitoring, 06 § Environments |
| release | runbook rehearsal (8.5), then the production deploy (Step 9): always the last tasks | 06 § Runbook |

Tier S: one scaffold task (a directory, the file, a lockfile if there are dependencies, `git init`); the rest only if Step 1's screening ran the matching step.

Each devops task names the law sections it executes and its verification with expected results. A task that creates anything outside the project directory, costs money, or is visible to others (a remote repository, cloud resources, DNS, branch rules, a deploy) is marked `Go: required` with what exactly needs the go. The orchestrator will not start it without the user's explicit go for that task.

**Test tasks.** One per component, whatever the component's grain: it covers every entry in the component (split by file when a component has more than about ten), every fixture of the operations the component delivers, and the kinds of tests Step 5 assigned. For tier L add a holdout test task per component (or one for the project) whose tests implementers never see.

**Code tasks.** Function grain: one task per function, in its layer. Component grain: one task per component, its layer being the highest layer among its functions, with its entries listed in internal layer order. Mixed: both.

**Dependencies.** Every task depends on the scaffold. A code task depends on its component's test task (tests exist before code is written; they are the backpressure) and on the tasks that implement the functions it calls outside its own task. A devops task depends on what it needs (checks on scaffold; environments on the last code task; release on 8.5). Two tasks never list the same file.

**Verification.** Exact commands per task, with the expected result where it is not simply "exit 0". Code: the task's tests, format, lint and type check on its files. Test: the new tests all fail against the stubs, plus the orchestrator's review. Devops: the law's expected results.

**Coverage.** Every function is in exactly one code task. Every component has a test task. Every decision in 03–06 maps to a devops task or is marked `manual (user)` with the reason. Tasks run layer by layer; tasks in the same layer may run in parallel when their files differ; devops tasks run alone.

Write the lane model classes (from `reference/defaults.md` § Subagent models), the commit policy and the grain decisions at the top of the Tasks section; the orchestrator copies them into the shared context.

## 7.7 Assemble the PRD

Write `agents/prd.md` from the template below. Copy, do not paraphrase: the success criteria, non-goals and constraints come from `01-user-intent.md` word for word; entries come from the stubs. Condense Steps 3–6 into § 2 with a pointer to the section of the law file that holds the detail. The PRD is read by agents that never open the conversation, and by the user, so it has to stand on its own, while the law files stay the authority for operations.

For tier S, the contract entries, fixtures and tasks all live inline; `agents/contract/` is not created.

## 7.8 Verify

Run `verify-contract.md` on the assembled PRD. In short: mechanical checks, a trace of every operation through the functions that deliver it, a task-coverage check, then an independent review, by a model from a different vendor where one is available. For tier L, and for tier M with sensitive data or destructive operations, also run its safety review. Loop until a review pass finds nothing blocking.

## 7.9 Freeze

1. Show the user a summary: counts of operations, components by grain, functions by tag, fixtures, and tasks by lane (listing the `Go: required` ones); the verification record; where to browse the HTML; and the size of the build (how many agents of each class).
2. Point them to what they should read personally: `docs/ARCHITECTURE.md`, the schema, and § 1 and § 5 of the PRD.
3. Ask for explicit approval to freeze.
4. From the project root run `bash <this skill's directory>/scripts/law.sh seal`.
5. If the project is already under version control, commit and tag `prd-v1.0.0`. Otherwise the scaffold task does this first.

From here on the only way to change these files is `amend.md`.

## PRD template

```markdown
# PRD — <project name>
Status: FROZEN · PRD v1.0.0 · <date> · approved by <user>

## 1. Idea
### Summary               3–5 sentences, from 01-user-intent.md
### Users and usage
### Success criteria      copied from 01; observable and checkable
### Non-goals
### Constraints
### First-party tools     name · interface · environments agents may use · pointer to 01
### Stack                 language and version; the dependency table from 04
### Tier

## 2. Operating decisions   one short block each, with a pointer to the law section
### Persistence           stores, data model, destructive operations and their guards → 03
### Security              sensitive data, baseline deviations, scanners → 04
### Testing               kinds of tests, tools, test doubles, coverage bar, environments, independence rules → 05
### Deployment            target, packaging, version control and PR rules, CI checks, environments, runbook → 06

## 3. Logical components
### Overview              component · purpose · files · depends on · grain · functions (n standard / n complex)
### <component>           purpose · owns · interface · depends on · files · grain and why · test task scope
(one block per component)

## 4. Contract
### Schema                paths under agents/contract/schema/ (tier S: inline)
### Types and errors      shared types, error types, constants, configuration keys
### Functions             tier S: full entries. M/L: function · file · component · layer · tag · purpose; entries live in agents/contract/stubs/
### Fixtures              operation · case · files
### Traceability          each success criterion and operation → the functions that deliver it

## 5. Tasks
### Lanes                 model class per lane; commit policy; parallelism rule
### Grain decisions       component · grain · reason
### devops                task entries
### test                  task entries
### code                  task entries, grouped by layer
### Coverage              every function → one code task; every component → a test task; every 03–06 decision → a devops task or "manual (user): reason"

## 6. Verification record
### Passes                checks run; reviewer and model; findings; resolution
### Safety review         findings and resolution, or "Not required (tier …)"
```

## Task entry format

The first line of a task is fixed-format so that the scripts can read it: checkbox, id, lane, grain, tag (code lane only), title, separated by ` · `. Ids are `D-nn` (devops), `T-nn` (test) and `C-nn` (code), numbered in intended order. The indented fields below it are free-form but always present.

```markdown
- [ ] C-07 · code · fn · standard · parse_duration
  - Files: src/util/duration.py
  - Entries: parse_duration
  - Layer: 0 · Depends on: D-01, T-02
  - Verify: `uv run pytest tests/util/test_duration.py -q -k parse_duration && uv run ruff check src/util/duration.py && uv run pyright src/util/duration.py`

- [ ] C-09 · code · component · standard · config
  - Files: src/config.py
  - Entries: load_config, env_override, validate_config (in this order)
  - Layer: 1 · Depends on: D-01, T-04, C-07
  - Verify: `uv run pytest tests/test_config.py -q && uv run ruff check src/config.py && uv run pyright src/config.py`

- [ ] T-02 · test · component · duration
  - Files: tests/util/test_duration.py
  - Entries: parse_duration, format_duration · Fixtures: parse-duration/*, format-duration/*
  - Kinds: unit per entry, fixture tests, property test on the parse/format round trip
  - Depends on: D-01
  - Verify: `uv run pytest tests/util/test_duration.py -q` — every test fails with NotImplementedError against the stubs

- [ ] D-02 · devops · checks · CI pipeline
  - Files: .github/workflows/ci.yml, Makefile, scripts/conformance_check.py
  - Law: agents/06-deployment.md § CI/CD, § Build; agents/04-security.md § Ongoing verification
  - Go: not required
  - Depends on: D-01
  - Verify: the pipeline runs on the scaffold branch and every check named in 06 § CI/CD is present and green; `make check` reproduces it locally
```

In the sealed PRD every task is `- [ ]`. Status is tracked only in the copy `.orchestrator/tasks.md`: `[~]` running, `[x]` done, and `BLOCKED(needs human): ` or `HOLD: ` after the checkbox.

## Done when

- Every operation is in the schema and every fixture validates against it.
- Every function has a complete entry, a tag and a layer, and passes the cold-implementer test. Every component has a grain and a reason.
- Every function is in exactly one code task, every component has a test task, every 03–06 decision has a devops task, and every task has exact verification.
- The stubs compile (M and L) and verification has passed with nothing blocking.
- The user explicitly approved the freeze and `law.sh seal` succeeded.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
