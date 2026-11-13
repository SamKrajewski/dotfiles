# Bug catalog

One entry per class the analysis step hunts for. For each class: what to look
for in the diff, how to confirm it before reporting, and a short example. Use
the class names exactly as written; they go into `finding.class` and the eval
cases match on them. Repo-specific classes live in
`.review/bug-catalog.local.md` and are appended to this list at review time.

Hunting means asking each class's question of every hunk, not reading the diff
once and waiting for something to jump out. Bugs that matter are rare (the
talk puts catastrophic ones at about 1 in 1,000 PRs), so the default outcome of
a careful pass is "nothing for this class".

When two classes fit one root cause, file it under the most specific one that
names the mechanism (`unit-encoding` over `contract-break` for a bytes-vs-
characters slip; `auth-bypass` over `intent-mismatch` for a missing login
check), and keep that choice on re-reviews: the class is part of the finding's
stable ID and of eval matching.

### `auth-bypass`

**Look for:** a new or changed route, handler, RPC method, GraphQL resolver,
queue consumer, or admin action without the authentication or ownership check
its neighbours have; a check moved after the side effect; a check that tests
the wrong subject (the caller instead of the resource owner); feature flags or
"internal" headers that skip auth.
**Confirm:** find the sibling handlers in the same file or router and compare
their first lines; trace the middleware chain for this path; at runtime level
3, call the endpoint unauthenticated and as a different user.
**Example:** `router.get('/orders/:id', getOrder)` added next to routes that
all start with `requireUser` and `assertOwns(order)`; `getOrder` loads by id
only. Any logged-in user reads any order.

### `off-by-one`

**Look for:** loop bounds (`<` vs `<=`), slice and substring ends, pagination
(`offset`, `limit`, `page * size`), inclusive vs exclusive date ranges, 0- vs
1-based indexes crossing a boundary (SQL, UI, protocol), `len - 1`, boundary
values in retries and backoff counts.
**Confirm:** compute the smallest and largest value by hand for a concrete
input (empty, one item, exactly `size` items, `size + 1`) and compare with the
intended result.
**Example:** `SUBSTR(id, 5, 3)` on a 3-character id returns an empty string;
the pipeline silently writes blank codes. Or `for i in range(1, len(xs))`
skipping the first element. (Counting the right things in the wrong unit is
`unit-encoding`, not off-by-one.)

### `null-empty`

**Look for:** a value that can be null, undefined, missing, or an empty
collection on a path that actually happens (first run, deleted parent,
optional field, failed lookup), then dereferenced or iterated as if present;
`.get()` defaults that mask a missing key; `first()` on an empty list; empty
string treated as present.
**Confirm:** name the realistic input that produces the empty value and
follow it to the crash or wrong result. "Could theoretically be null" is not a
finding.
**Example:** `user.profile.timezone` where `profile` is created lazily on
first login; new users hit the dashboard before it exists.

### `async-race`

**Look for:** a missing `await` (promise discarded, errors lost, ordering
assumed); check-then-act without a lock or transaction (read balance, then
write); retries of a non-idempotent operation (charge, send, insert); shared
mutable state across concurrent handlers; fire-and-forget work whose result the
next line depends on; `Promise.all` where one failure should stop the rest.
**Confirm:** write the interleaving: two requests, or one request plus one
retry, step by step, and show the wrong final state.
**Example:** `charge(customer)` times out after the bank accepted it; the
retry calls `charge` again with no idempotency key. The customer pays twice.

### `data-migration`

**Look for:** destructive schema changes (drop column, narrow type, add NOT
NULL without default) that break the still-running old code; code that reads a
column the migration has not added yet (deploy-order dependency); backfills
without batching on large tables; migrations that lock a hot table; data
transforms that lose precision or time zones; irreversible migrations without
a down path.
**Confirm:** write the deploy sequence (migration first vs code first) and
check both orders; check row counts and lock behaviour of the statements.
**Example:** PR renames `users.email` to `primary_email` in one migration while
the previous release's pods still select `email` during the rolling deploy.

### `swallowed-error`

**Look for:** `catch` that logs and continues where the caller assumes
success; success returned after a failed write; errors converted to default
values; `finally` that overwrites a thrown error; broad `except Exception`
around the whole function; ignored return codes; promise rejections with no
handler.
**Confirm:** make the inner operation fail in your head (network down, row
missing, permission denied) and follow what the caller sees and stores.
**Example:** `try { await db.save(order) } catch (e) { log(e) } return
{ok: true}`; the UI shows "Order placed" and the order does not exist.

### `unbounded`

**Look for:** a query inside a loop (N+1), a list loaded in full where it can
be large, missing `LIMIT`, pagination removed, unbounded caches or arrays
appended per request, recursion without depth limit, regexes with
catastrophic backtracking on user input, timeouts removed.
**Confirm:** state the realistic size (users × items, rows after a year) and
the resulting number of queries, bytes, or seconds.
**Example:** `for order in orders: order.customer.name` with lazy loading on a
page listing 500 orders issues 501 queries.

### `injection-secrets`

**Look for:** user input concatenated into SQL, shell commands, HTML, URLs
(SSRF), file paths (traversal), log lines (log injection), or template
strings; deserialisation of untrusted data; secrets, tokens, or keys committed,
logged, or sent to analytics; permissive CORS; disabled TLS verification.
**Confirm:** write the malicious input and show where it is interpreted; for
secrets, show the file or log sink.
**Example:** `open(f"uploads/{filename}")` with `filename` from the request;
`../../etc/passwd` reads outside the upload directory.

### `contract-break`

**Look for:** a changed function signature, enum, status code, JSON field,
proto, event schema, config key, environment variable, CLI flag, or database
column with consumers that were not updated; renamed or removed exports;
changed default values; stricter validation on an existing input.
**Confirm:** search consumers by exact symbol or key name (in this repo and
in `context.related_repos`); list which were updated and which were not.
**Example:** `getUser(id)` becomes `getUser({id})`; two of three call sites
updated; the third passes a string and gets `undefined` back.

### `incomplete-change`

**Look for:** a fix or rename applied to one of several parallel places
(copy-pasted handlers, per-platform implementations, a constant duplicated in
tests or docs, feature flag checked in two layers); a new field added to the
model but not to the serializer, the validator, or the migration; a new enum
value not handled in a `switch` with no default.
**Confirm:** enumerate the parallel sites by pattern and tick each one off.
**Example:** the retry limit changed from 3 to 5 in the worker but not in the
timeout calculation that assumes 3 attempts.

### `ui-render`

**Look for:** fixed heights or widths, content that grows (long names,
translations), absolute positioning, overflow hidden on containers with
actions, modals taller than a phone screen, focus or scroll traps, elements
that depend on hover, conditional rendering that hides a primary action in a
state the user can reach.
**Confirm:** at runtime level 4, render the flow at 390×844 and desktop and
screenshot; below level 4, reason from the CSS and say the confidence is
`traced` at most.
**Example:** the sign-up form gains a terms checkbox; at 390×844 the submit
button sits below the fold inside an `overflow: hidden` card.

### `unit-encoding`

**Look for:** a quantity handled in the wrong unit or representation: bytes
vs characters (slicing, length checks, column limits), seconds vs
milliseconds, cents vs dollars, UTC vs local time, degrees vs radians, 0- vs
1-based positions passed across a boundary, floats carrying money, text
compared or sorted without normalisation (case, Unicode form, trailing
whitespace), string identity used where equality was meant.
**Confirm:** compute one concrete value in both units and show they differ
where the code assumes they agree (`"Christopher Sebastián"` is 21 characters
and 22 bytes; `[:20]` on the bytes splits the `á`).
**Example:** `name.encode("utf-8")[:20].decode("utf-8")` for a "20-character"
name box: 3-byte scripts lose two thirds of the name and some inputs raise
`UnicodeDecodeError`.

### `ai-artifacts`

**Look for:** calls to APIs, flags, or library functions that do not exist in
the pinned version (hallucinated); `TODO`/`pass`/`NotImplemented` stubs left
in a path the feature needs; tests weakened to pass (assertions removed,
expected values changed to the buggy output, tests skipped, snapshots
blindly updated); mock or fixture data that leaked into production code;
duplicated helpers that already exist in the repo; plausible but wrong
comments.
**Confirm:** check the API against the installed version (lock file,
`node_modules`, docs); diff the test file's assertions before and after; run
the test if the environment allows.
**Example:** `expect(total).toBe(1099)` changed to `toBe(1100)` in the same
PR that introduced a rounding change, with no explanation.

### `intent-mismatch`

**Look for:** the code works but does not do what the ticket, PR description,
or ADR asked: a required behaviour missing, an extra behaviour nobody asked
for, a contradiction with a documented decision, unrelated changes bundled in,
a narrower or wider scope than requested (one locale instead of all; all users
instead of the flagged cohort).
**Confirm:** quote the requirement and the code that fails to meet it.
Without a stated intent there is no mismatch; report `intent.status: unknown`
instead.
**Example:** ticket: "retry failed webhooks up to 3 times with backoff". PR:
retries 3 times immediately, and also changes the webhook timeout, which was
not requested.
