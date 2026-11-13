# Step 2 — Inputs / Outputs

**Goal:** pin down the project's boundary: everything that goes in, everything that comes out, and what happens when the input is wrong.
**Writes:** `agents/02-inputs-outputs.md`, plus a draft schema file beside it when one is natural (for example `agents/02-openapi.yaml`)
**Runs:** always.

This is the first draft of the contract. Step 7 hardens it into the PRD's schema, and the examples collected here become the test fixtures used in Step 8, so precision now pays twice.

## 1. Identify the interfaces

A project can have several. Document each in the format native to it. The choice is yours, as long as the result is clear and a tool can read it.

| Interface | Document it as | Be sure to ask |
|-----------|----------------|----------------|
| HTTP / REST API | OpenAPI 3.1 | Each endpoint; which operations each supports; request and response bodies; status codes; auth; pagination; idempotency; versioning |
| GraphQL | Schema (SDL) | Queries, mutations, subscriptions; nullability; error shape |
| gRPC / RPC | Protocol Buffers | Services, methods, streaming, error codes |
| Events / queues | AsyncAPI or JSON Schema | Topics, payloads, ordering, retries, duplicates |
| CLI | Usage text plus a table of flags and exit codes | Commands, flags, stdin/stdout/stderr, exit codes, environment variables, config file |
| Library | Signatures with doc comments (Javadoc, docstrings, TSDoc, rustdoc) | Public functions and types, error types, thread safety |
| Files / batch | JSON Schema, a column spec, sample files | Format, encoding, delimiter, size, what happens to bad rows |
| Web UI | Page list: for each page, the data shown and the actions offered | Routes, forms, loading/empty/error states, who can see what |
| Script | Arguments, files read, files written, exit code | What it prints; what it changes on disk |

## 2. Specify every operation

For each endpoint, command, public function or file:

- **Input:** every field, with type, required or optional, valid values, limits and default.
- **Success output:** the exact shape, and the ordering if it is a list.
- **Failure output:** each way it can fail, and what the caller sees (status code, exit code, message).
- **Side effects:** what it changes, and whether repeating the call is safe.
- **Who may call it,** when there are users or roles.

Settle the details that usually stay implicit: units, time zones, date formats, encodings, null versus absent, case sensitivity, maximum sizes, sort order. Each one left open becomes a guess by a low-power model later.

## 3. Collect examples

Ask the user for real examples. Invent them only if they have none, and have them confirm yours. For each operation collect a typical case, an edge case and a failure, as concrete input → expected output pairs. For tier S, two or three examples for the whole script are enough.

Examples do two jobs. They expose misunderstandings that prose hides, and in Step 7 they become fixture files that the implementation must reproduce exactly.

## 4. Check against Step 1

- Every success criterion in `01-user-intent.md` is reachable through some operation here.
- Nothing here serves a non-goal.
- Every first-party tool the project consumes appears as an input or output with its interface.

## Output template

```markdown
# 02 — Inputs / Outputs
Status: APPROVED · <date> · approved by <user>

## Interfaces          one line each: kind, audience, documentation format
## Operations          per operation: input, success output, failures, side effects, access
## Shared types        data shapes used by more than one operation
## Conventions         units, time zones, encodings, null handling, limits, ordering
## Examples            per operation: input → expected output (typical, edge, failure)
## Draft schema        path to the schema file, or "inline above"
```

## Done when

- Every operation has its input, success output and failure outputs written down.
- Every operation has at least one confirmed example (tier S: the script as a whole does).
- No "TBD", "etc." or "and so on" remains.
- The user has approved it.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
