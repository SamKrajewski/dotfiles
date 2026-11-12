# Step 7 — Contract Freeze

**Goal:** turn the earlier decisions into one exact, verified contract (every interface as data, every function specified) and seal it.
**Writes:** `agents/07-contract.md`, `agents/contract/`, `docs/ARCHITECTURE.md`, `agents/MANIFEST.sha256`
**Runs:** always. Tier S writes everything into `agents/07-contract.md` and skips 7.5.

This is the last point where changing your mind is cheap. After the freeze, low-power models implement what is written here, literally, with no access to this conversation. Anything vague becomes a wrong guess and anything missing becomes an amendment, so take the time. This step is allowed to be slow.

**The test for every entry:** could a model that has never seen this conversation implement it correctly from the entry alone, plus the signatures of what it calls? If not, the entry is not finished.

The contract refines the earlier law files and must never contradict them. If it has to, the earlier file is amended first.

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

Break the problem into digestible pieces, by logical component or by file. Every major service, complex task and reusable feature is a component. For each one:

- **Purpose** in one sentence. If it needs "and", consider splitting it.
- **Owns:** the data and responsibilities that belong to it alone.
- **Interface:** what other components may call.
- **Depends on:** which components it may call. Dependencies must not form a cycle.
- **Files:** where it lives.

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

**Tagging.** The tag picks the model that implements the function in Step 8. Tag a function `complex` if, after decomposition, it still coordinates several calls with error handling between them; involves concurrency, transactions or retries; implements a non-trivial algorithm; or is security-critical (authentication, permission checks, sanitizing input). Everything else is `standard`.

**Decomposing.** If a function cannot be described in about 15 lines, has more than one kind of side effect, or mixes decisions with input/output, run `decompose-function.md` on it. A generic endpoint handler is the typical case. If more than about a fifth of the functions end up `complex`, decompose further: the plan is carrying too little of the difficulty.

## 7.5 Contract format (tiers M and L)

Save the contract as real, compilable interface stubs with doc comments, in the language's standard documentation format: Javadoc, Python docstrings, TSDoc, rustdoc, Go doc comments, Doxygen. Put them in `agents/contract/stubs/`, mirroring the source tree, with every body replaced by a "not implemented" error.

- The stubs must compile or type-check. That proves the types line up before any body exists.
- Generate HTML from them (`reference/defaults.md` § Libraries, "Contract docs to HTML") into `docs/contract/` so the user can browse the contract. The HTML is a build product and is not sealed.

Tier S: the entries live as a section of `agents/07-contract.md`. No stubs, no HTML.

## 7.6 Verify

Run `verify-contract.md`. In short: mechanical checks, a trace of every operation through the functions that deliver it, then an independent review, by a model from a different vendor where one is available. For tier L, and for tier M with sensitive data or destructive operations, also run its safety review. Loop until a review pass finds nothing blocking.

## 7.7 Build order

Sort the functions into layers. Layer 0 calls no other contract function; layer N calls only layers below it. Record layer, function, file and tag. This table is the work order for Step 8, so that nothing is left to decide during implementation.

## 7.8 Freeze

1. Show the user a summary: counts of operations, components, functions by tag, and fixtures; the verification record; where to browse the HTML; and the size of the build (how many subagents of each class).
2. Point them to what they should read personally: `docs/ARCHITECTURE.md` and the schema.
3. Ask for explicit approval to freeze.
4. From the project root run `bash <this skill's directory>/scripts/law.sh seal`.
5. If the project is already under version control, commit and tag `contract-v1.0.0`. Otherwise Step 8.1 does this first.

From here on the only way to change these files is `amend.md`.

## Output template

```markdown
# 07 — Contract
Status: FROZEN · contract v1.0.0 · <date> · approved by <user>

## Schema               paths under agents/contract/schema/ (tier S: inline)
## Components           component · purpose · files · depends on
## Functions            tier S: full entries. M/L: function · file · tag · purpose (entries live in the stubs)
## Types and errors     shared types, error types, constants, configuration keys
## Fixtures             operation · case · files
## Traceability         each requirement and operation → the functions that deliver it
## Build order          layer · function · file · tag
## Verification record  checks run; reviewer and model; findings; resolution
## Safety review        findings and resolution, or "Not required (tier …)"
```

## Done when

- Every operation is in the schema and every fixture validates against it.
- Every function has a complete entry and a tag, and passes the cold-implementer test.
- The stubs compile (M and L) and verification has passed with nothing blocking.
- The user explicitly approved the freeze and `law.sh seal` succeeded.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
