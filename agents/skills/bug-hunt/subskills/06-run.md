# Step 6 — Run what the environment allows

**Goal:** turn `traced` candidates into `confirmed` ones (or kill them) by
running code: tests, throwaway tests, the app, the browser. Some bugs are
invisible in a diff and only show when the code runs. Record the level reached
so the reader knows what was and was not exercised.
**Writes:** updates to `tmp/draft.json` (`confidence`, `verified_by`,
`evidence`, `coverage.runtime_level`, `coverage.checked/not_checked`);
throwaway tests and screenshots under `.review/tmp/`.
**Runs:** every depth, to the level the depth and the environment allow.

The level table, prerequisites and per-level procedure are in
`references/testing.md`. This step decides how far to climb and applies it.

## How far to climb

| Depth | Minimum | Beyond the minimum |
|---|---|---|
| `light` | level 0 | level 1 if a test command is already known and fast |
| `standard` | level 1 whenever a test command exists; level 2 for every `critical`/`high` candidate | level 3/4 when `testing.start` / a browser tool and `flows.yaml` exist |
| `deep` | level 2 for every `critical`/`high` candidate; level 3 when `testing.start` exists; level 4 when a browser tool and a matching flow exist | if the prerequisites are missing, say so in the report and recommend setting them up (`subskills/setup.md`) |

Find the commands in `.review/config.yaml` (`testing.*`). If they are blank,
look for the obvious ones (`Makefile`, `package.json` scripts, `pytest`,
`go test ./...`, Blaze targets for the changed packages) and record what you
used in `coverage.checked`; propose adding it to the config in the report.

If a configured command cannot run in this environment (runner not
installed, no network, no database), do not install packages or change the
environment to make it run. Use the smallest substitute that executes the
same tests (import the test module and call its functions; a standard-library
runner; the single Blaze target), name the substitute in `coverage.checked`,
and list the configured command as not run in `coverage.not_checked`. If no
substitute exists, stay at the level you reached and say so.

Keep the tree clean while running: set `PYTHONDONTWRITEBYTECODE=1` (or the
language's equivalent), run from the repo root, and afterwards remove any
caches or build outputs the run created outside `.review/tmp/`.

## Apply the results

- A level 2 test that fails for the predicted reason: `confidence:
  confirmed`, `verified_by: "level 2 test <path> fails on head: <one-line
  reason>"`. One that passes: the candidate is wrong or untraced; drop it, or
  keep it as `suspected` only if critical/high and the test could not reach
  the condition (say why in `evidence`).
- A level 3 request that shows the wrong behaviour: `confirmed`, with the
  request and response in `evidence`.
- A level 4 flow expectation that fails: `confirmed`, with the screenshot path
  in `evidence`.
- A failing existing test (level 1) that the diff caused: a finding in its own
  right if it is not already a candidate; class by root cause.
- Record `coverage.runtime_level` as the highest level actually run, and for
  each level not reached add one `not_checked` line naming what it would have
  covered ("level 3: endpoints not exercised, no start command").

## Safety

Sandbox or disposable environment only. No production, no shared staging, no
real credentials or customer data. Never push to, amend, or rebase the branch
under review. Throwaway tests live under `.review/tmp/` (gitignored) and stay
there as the regression test to hand the user with the fix; nothing from this
step is written into the tracked tree or committed.

## Done when

- `coverage.runtime_level` is set and every unreached level has a
  `not_checked` line.
- Every `critical`/`high` finding is `confirmed`, or its `evidence` says why
  it could not be confirmed.
- The app, if started, is stopped; `git status` (or `jj status`) shows
  nothing new outside `.review/`.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
