# Autonomous testing levels

Some bugs are invisible in a diff: the React code reads fine and the button is
hidden on a phone; the auth check looks present and is skipped by a
middleware ordering. Climb as far as the environment allows, record the level
reached in `coverage.runtime_level`, and list what the missing levels would
have checked under `coverage.not_checked`.

| Level | Do | Needs | Raises confidence to |
|---|---|---|---|
| 0 | Read only | nothing | `traced` at most |
| 1 | Type check, lint, and run the tests for the changed files | `testing.test` (or an obvious test command) | — (a passing suite proves little; a failing one is evidence) |
| 2 | Write a throwaway failing test for each `critical`/`high` candidate | level 1 | `confirmed` when the test fails on head and the failure is the predicted one |
| 3 | Boot the app; hit changed endpoints, including unauthenticated and as the wrong user | `testing.start`, `testing.health_url` | `confirmed` for `auth-bypass`, `contract-break`, `swallowed-error`, `null-empty` |
| 4 | Drive the matching flows from `flows.yaml` in a browser at phone (390×844) and desktop sizes; screenshot | a browser tool, a flow map | `confirmed` for `ui-render`, `intent-mismatch` on UI behaviour |

## Prerequisites (the hard part)

- **One script that builds and starts the app from a clean checkout.**
  Record it in `testing.setup` and `testing.start`. Without it levels 3 and 4
  are impossible, and discovering how to boot the app during a review is a
  cost the reviewer pays every time. Set it up once, in the `setup` subskill.
- **A flow map** (`.review/flows.yaml`): flows with the paths that trigger
  them, steps in plain instructions, and expectations including layout at
  phone size.

## How to run each level

**Level 1.** Prefer the repo's own command (`testing.test`, a `Makefile`,
`package.json` scripts, `pytest`, `go test ./...`, Blaze targets). Restrict to
changed packages where the runner allows it; a full suite is fine if it is
under a few minutes. Capture failures verbatim into `evidence`.

**Level 2.** For each `critical`/`high` candidate, write the smallest test
that would fail if the finding is real, under `.review/tmp/` (gitignored),
importing the repo's modules from there (or in a temp copy of the relevant
test file). Run it on head. A test that fails for the predicted reason makes
the finding `confirmed`; one that passes means the finding is wrong or
untraced: drop it or demote it to `suspected` with the test named in
`evidence`. Leave the test under `.review/tmp/` and offer it to the user as
the regression test for the fix; never add it to the tracked tree or commit
it to the branch under review.

**Level 3.** Start the app with `testing.start`, wait for `health_url`, then
exercise the changed endpoints: happy path, unauthenticated, as a different
user, with empty or oversized inputs. Record each request and response in
`evidence`. Stop the app when done.

**Level 4.** Select flows whose `paths` match the changed files. Run each at
every size in `sizes` (default 390×844 and 1440×900), check every `expect`
line, and keep screenshots in `tmp/screenshots/` referenced from `evidence`.

## Safety

- Sandbox or disposable environment only: a container, a throwaway database,
  a local port. Never production, never staging that others use.
- No real credentials, tokens, or customer data. If the app needs secrets to
  boot, use the test fixtures the repo provides or stop at level 2.
- Never push to, amend, or rebase the branch under review. Throwaway tests
  and screenshots live under `.review/tmp/`.
- Respect the budget for the depth (`limits.budget_usd`); when it is spent,
  finish the report with what is known and list the rest as not checked.

## Done when

A fixture PR that hides a button at phone size is caught at level 4, and a
fixture PR that removes an auth check is confirmed at level 3. Keep both as
eval cases (`kind: synthetic`).
