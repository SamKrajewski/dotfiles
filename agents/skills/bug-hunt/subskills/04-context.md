# Step 4 — Load context

**Goal:** give the analysis exactly the system knowledge it needs (invariants,
consumers, the few files that matter) and nothing else. Grep is imprecise and
expensive; a knowledge base read first is cheaper and catches the bugs that
need system knowledge ("is this path authenticated?").
**Writes:** `.review/tmp/context.md`, the context pack.
**Runs:** `standard` and `deep`. `light` skips it and records "no context
loaded" under `coverage.not_checked`.

Format, freshness rules and how to build the KB are in
`references/context.md`. This step is the review-time procedure.

## Procedure

1. **Match the KB.** Read `.review/kb/INDEX.md`; match the changed paths
   against its globs; read only the matching entries. Note any entry whose
   `last_verified_sha` predates changes to its paths: skim those changes and
   correct the entry before relying on it.
2. **Pull the invariants.** Copy the matched entries' **Invariants**,
   **Consumers** and **Past incidents** into the pack. Each invariant will be
   checked against every hunk in step 5.
3. **Enumerate consumers of changed public symbols.** For every function,
   method, endpoint, event, config key, flag, column or exported constant whose
   signature or meaning changed, search by **exact name** (Code Search in
   google3, `grep -nw` in a small repo, the editor's symbol search). List the
   call sites found and whether the diff updated each. Stop at enumeration;
   the judgement happens in step 5.
4. **Respect the cap.** `limits.max_context_files` (default 25) files beyond
   the diff. Past the cap, rank the candidates by how directly they touch a
   changed symbol or invariant (a small-tier model if the host can route to
   one, otherwise a quick pass yourself) and read only the top ones. Count
   what you read.
5. **Write the pack.** `tmp/context.md`:

```markdown
# Context pack — <branch> @ <sha>

## Knowledge base entries used
### <entry> (verified at <sha>; stale: yes/no)
Invariants: …
Consumers: …
Past incidents: …

## Changed symbols and their consumers
| Symbol | Kind | Consumers found | Updated in this diff |
|---|---|---|---|
| getUser | function | web/api.ts:40, jobs/sync.ts:88, cli/user.ts:12 | 2 of 3 |

## Excerpts
### path/to/file.ts:30-58 — why it is here
```<code>```

## Not loaded
- <what you chose not to read and why: over cap, generated, vendored>
Files read: 14
```

## No knowledge base yet

Do steps 3 to 5 from the code for the subsystems the diff touches. Keep notes
on what you had to discover (how the middleware is ordered, which table is
large). After step 7, write one entry per touched subsystem that has none
(`templates/kb-entry.md`, plus a row in `kb/INDEX.md`), with only invariants
you verified against the code during this review, and list the new files in
the report. Edits to entries that already exist are proposed in `kb_updates`
instead and applied when the user accepts. The first review in a repo is the
most expensive one; the KB is how the next one is cheaper.

## Done when

- `tmp/context.md` exists with the invariants to check, the consumer table,
  and a files-read count under the cap.
- Stale entries are either corrected or marked stale in the pack.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
