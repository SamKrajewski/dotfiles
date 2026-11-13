# Codebase context: the knowledge base

Grepping a repository at review time is imprecise and expensive, and some
bugs cannot be judged from the diff at all: is this code path authenticated?
Is this table large? The answer is a small knowledge base (KB) that is written
once, kept fresh by reviews, and read before any searching.

## Layout

```
.review/kb/
  INDEX.md            table: entry file, path globs, last verified SHA
  authentication.md   one entry per subsystem, 8 to 30 entries, each < 150 lines
  billing.md
  ...
```

Entry format (`templates/kb-entry.md`):

```markdown
---
subsystem: authentication
paths: ["src/auth/**", "src/middleware/session.ts"]
last_verified_sha: abc123
---
## How it works
## Key flows          (a small diagram)
## Files and entry points
## Invariants         ("every /api/admin/* handler calls requireAdmin first")
## Consumers          (callers, other services and repos)
## Past incidents
```

The **Invariants** section is the valuable part. Write each invariant as a
sentence a reviewer can check a hunk against: "every write to `ledger` goes
through `post_entry()`", "amounts are integers in minor units", "handlers under
`/internal/` are only reachable from the mesh". Vague descriptions produce no
findings; invariants produce the best ones.

## At review time

1. Match the changed paths against `INDEX.md` globs and read only the
   matching entries. Record them in `coverage.kb_entries`.
2. Check every changed hunk against the invariants of those entries. A hunk
   that breaks an invariant is a finding candidate with the invariant as its
   evidence.
3. Look up callers and consumers of changed symbols by **exact name** (the
   function, key, column, flag), not by broad keyword sweeps. One precise
   search per changed public symbol; stop when the consumers are enumerated.
4. Stay under `limits.max_context_files` (default 25) files read beyond the
   diff. Over the cap, rank candidates (a small model if the host can route
   to one, otherwise a quick relevance pass by the current model) and read
   only the top ones. Record `coverage.files_read`.
5. Write the result as the **context pack** at `tmp/context.md`: the matched
   KB entries' invariants and consumers, the caller lists, and any file
   excerpts the analysis needs, each with a path. The analysis step reads the
   pack, never raw search output.

When there is no KB yet, still do steps 3 to 5 from the code. Then, before
the report, write the entry for each touched subsystem that has none (use
`templates/kb-entry.md`, add a row to `INDEX.md`, set `last_verified_sha` to
the head you reviewed): new entries are additive and you have just verified
their contents against the code, so there is nothing for the user to approve.
Edits to existing entries are different: propose them in `kb_updates` and
apply them when the user accepts.

## Keeping it fresh

- An entry whose `paths` changed since its `last_verified_sha` is stale:
  skim the changed files against the entry and fix anything wrong before
  trusting it. Bump the SHA.
- When a change alters a documented flow, invariant, or consumer, propose the
  KB edit in `kb_updates` (shown in the report). Apply it when the user
  accepts. Missing entries are written, not proposed (above).
- Every incident or escaped bug adds a line under **Past incidents** and,
  when a pattern emerges, a class in `bug-catalog.local.md`.

## Building the KB (first run or `setup` subskill)

Aim for 8 to 30 entries. Sources, in order of value: existing architecture
docs and ADRs; the incident or postmortem list (ask the user); the module
boundaries visible in the tree (`src/<x>/`, services, packages); the
top-level routers, schemas, and job definitions. For each entry, fill
**Invariants** from what the code actually enforces (middleware order,
constraints, assertions) and from what incidents showed was assumed. Verify
each sentence against the code before writing it: the KB is trusted at review
time, so a wrong invariant produces a confident wrong finding.

Done when files read per review drops on the eval set with catch rate equal
or better. That is the measurement; a KB that does not cut reading is not
yet doing its job.
