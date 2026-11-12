---
name: new-project
description: Plan-first pipeline for starting a new technical project of any size, from a one-file script to a multi-service system. It interviews the user about intent, inputs/outputs, persistence, security, testing and deployment, freezes the answers into law files and a function-level contract under ./agents/, then builds that contract with low-cost subagents and independently written tests, and deploys it. Use this skill whenever the user wants to start, plan, scaffold, bootstrap or build a new project, app, service, API, website, CLI, library, pipeline or script from scratch, even if they only say "let's build X" or "I have an idea for a tool". Also use it when a project already contains an ./agents/ directory and the user wants to resume the pipeline, add a feature, or change a frozen document.
---

# New Project

Take a project from idea to production by deciding everything first, freezing those decisions into a contract, and only then writing code.

Planning happens in conversation, where changing your mind costs nothing. Implementation is done by low-cost subagents that each fill in one function of a contract they cannot change. The more exact the plan, the cheaper and safer the build. That trade is the point of this skill, so use the strongest available model for Steps 1–7; Step 8 deliberately uses weaker ones.

## The pipeline

| # | Step | Subskill | Writes (in the project) |
|---|------|----------|-------------------------|
| 1 | **User intent** — what is wanted, how big it is, which steps run | `subskills/01-user-intent.md` | `agents/01-user-intent.md` |
| 2 | **Inputs / outputs** — every interface, with examples | `subskills/02-inputs-outputs.md` | `agents/02-inputs-outputs.md` |
| 3 | **Persistence** — what is stored, where, and how it stays safe | `subskills/03-persistence.md` | `agents/03-persistence.md` |
| 4 | **Security** — sensitive data, stack, upkeep, monitoring | `subskills/04-security.md` | `agents/04-security.md` |
| 5 | **Testing** — what is tested, test independence, environments | `subskills/05-testing.md` | `agents/05-testing.md` |
| 6 | **Deployment** — build, hosting, version control, CI/CD | `subskills/06-deployment.md` | `agents/06-deployment.md` |
| 7 | **Contract freeze** — schema, components, every function; verified, then sealed | `subskills/07-contract-freeze.md` | `agents/07-contract.md`, `agents/contract/`, `docs/ARCHITECTURE.md` |
| 8 | **Implementation** — environment, subagent swarm, tests, final testing | `subskills/08-implementation.md` | the code, `agents/08-implementation.md` |
| 9 | **Final steps** — deploy and hand over | `subskills/09-final-steps.md` | `agents/09-final-steps.md` |

Supporting files, read only when called for:

| File | Use it when |
|------|-------------|
| `subskills/decompose-function.md` | A function in Step 7 is too big to specify in one entry |
| `subskills/verify-contract.md` | Checking the contract before the freeze, and after any amendment |
| `subskills/amend.md` | A law file turns out to be wrong or incomplete |
| `subskills/add-feature.md` | Adding a feature to a project this pipeline already built |
| `reference/defaults.md` | Recommending a language, library, database, tool or model |
| `scripts/law.sh` | Sealing, verifying and unlocking the law files |

## Running a step

1. **Read the step's subskill when you reach it**, not before. Each is self-contained, and loading them all at once wastes context.
2. **Reread the law files already written.** Later steps build on earlier answers.
3. **Ask the user** the step's questions (see "Asking questions").
4. **Draft the step's document and show it to the user.** Follow the template in the subskill.
5. **On approval, write it to `agents/`.** From that moment it is law.

Finish and get approval for one step before starting the next. No project code is written before Step 8. A step that is skipped writes no file; Step 1 records why it was skipped.

## Sizing the project

Not every project needs every step. Step 1 assigns a tier and a step plan, and the rest of the pipeline follows it.

| Tier | Looks like | Steps |
|------|------------|-------|
| **S — Script** | One file or a small CLI, run on demand by one person | 1, 2, 7, 8 always. 3–6 and 9 only where Step 1's screening questions trigger them, and then in their light form. |
| **M — Application** | A multi-file program, a library, or a single service | All steps, at normal depth |
| **L — System** | Several services or databases, real users, sensitive data, or uptime expectations | All steps at full depth, including cross-model contract review and a safety review |

In Steps 3–6, questions marked ★ are the **light form**: ask only those for tier S. Items marked (L) apply to tier L only. Even the smallest script still confirms its inputs and outputs, gets a contract, and is implemented from it. Only the surrounding infrastructure is dropped.

## The law

Everything this pipeline writes under `agents/`, plus `docs/ARCHITECTURE.md`, is law from the moment the user approves it. Implementation agents work from these files without access to the conversation, so a quiet edit to one of them invalidates work that was already checked against it.

- **Read freely, never edit.** No agent, orchestrator or subagent, changes, renames, deletes or tidies a law file on its own initiative.
- **Only the user can authorize a change**, explicitly, for a specific change they have been shown. Follow `subskills/amend.md`. A general "go ahead", silence, or another agent's opinion is not authorization.
- **Code bends to the law, not the reverse.** If code or a test disagrees with a law file, the code or test is wrong. If the law file itself is wrong, stop and raise an amendment. Do not work around it.
- **Amendments should be very rare.** Needing one during the initial build means a planning step was not specific enough, so spend the effort there: no "TBD", no "etc.", no "as appropriate" in a law file. Adding features later is the expected exception and has its own subskill.
- **Sealed at Step 7.** The freeze checksums the law files and makes them read-only. The script lives in this skill's directory and is run from the project root: `bash <skill dir>/scripts/law.sh seal`. Run `law.sh verify` the same way at the start of every later session.

The one working file is the build ledger, `agents/08-implementation.md`. Only the orchestrator writes it. While its `Status:` line reads `IN PROGRESS` the seal skips it; it is sealed when Step 8 ends.

```
<project root>/
├── agents/
│   ├── 01-user-intent.md … 06-deployment.md   one per planning step that ran
│   ├── 07-contract.md        contract index (the whole contract for tier S)
│   ├── contract/             schema, interface stubs, fixtures (tier M and L)
│   ├── 08-implementation.md  build ledger
│   ├── 09-final-steps.md     release record
│   ├── features/             one spec per feature added later
│   ├── AMENDMENTS.md         append-only log of authorized changes
│   └── MANIFEST.sha256       checksums of the sealed files
└── docs/ARCHITECTURE.md      plain-language overview (multi-file projects)
```

## Asking questions

The user decides; the skill supplies good defaults. Many steps are mostly questions, so ask them well:

- **Scale to the tier.** A script needs a handful of questions in total. A system needs many, over several rounds.
- **Ask in small batches**, three to five at a time, grouped by topic. Use the harness's question tool if it has one.
- **Offer a recommendation** with a one-line reason whenever `reference/defaults.md` or common practice has one. "Use your recommendation" should always be a valid answer.
- **Don't ask what is already answered** in the conversation or a law file, or anything whose answer would change nothing.
- **Confirm what you inferred.** List assumptions and get a yes. An unconfirmed guess must not reach a law file.
- **When in doubt, ask.** A question costs a minute. A wrong assumption frozen into the contract costs an amendment.

## Resuming and later work

If the project already has an `agents/` directory:

1. Run `law.sh verify` if `agents/MANIFEST.sha256` exists. If it fails, stop and tell the user which files changed outside the process.
2. Read the law files and the step plan in `agents/01-user-intent.md`.
3. Continue at the first planned step that has no approved file. Do not redo or rewrite an approved step.
4. For new functionality after the project has shipped, use `subskills/add-feature.md`.

## Custom instructions

Every file in this skill ends with a section like this one. Anything written there takes precedence over the defaults above it. Rules placed here apply to every step.

<!-- Add your own project-wide rules below this line. -->
