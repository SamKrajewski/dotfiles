# Evals — the gate on every change to the reviewer

**Goal:** know whether a change to the prompt, the models, the routing or the
knowledge base made the reviewer better or worse. Small prompt edits swing
comment volume, and the bugs that matter are rare (the talk: about 1 in 1,000
PRs), so without a dataset there is no way to tell. Build this before tuning
anything else.
**Writes:** `.review/evals/cases/<id>/case.yaml`,
`.review/evals/reports/<timestamp>.{json,md}`.

## Case format

`templates/eval-case.yaml`:

```yaml
id: 2025-03-double-charge
kind: bug                 # bug | clean | synthetic
base_sha: abc123
head_sha: def456
author_family: gpt        # if known
intent: ""                # optional ticket/PR text to hand the reviewer
expected:
  - file: src/billing/charge.ts
    lines: [88, 104]
    class: async-race
    note: retry is not idempotent
```

A finding matches an expected bug when it is in the same file, its lines
overlap (within `evals.line_tolerance`), and its class is the expected one (or
one of `accept_classes`). Clean controls have no `expected`; any finding on
them is a false positive.

## Seeding (aim for 20+ bug cases and 10 clean controls)

1. **Incidents and postmortems** from the user: the PR that introduced each
   one becomes a case, with the class from its root cause.
2. **Git history:** `python3 <skill dir>/scripts/run_evals.py mine --clean
   --write` finds `revert|hotfix|regression|incident|fix` commits, blames the
   removed lines back to the commit that introduced them, and writes draft
   cases (`class: TODO`, lines to check). Review each draft: set the class,
   trim the expected list to the real bug, delete the ones that are not bugs.
3. **Synthetic:** for every catalog class with no real example, take a clean
   commit, inject one bug of that class on a scratch branch, commit it, and
   record the SHAs with `kind: synthetic`. Keep the fixtures required by
   `references/testing.md` here too (hidden button at phone size, removed
   auth check), plus one correct-but-off-spec case with an `intent` that the
   code does not satisfy, and one case with no description at all whose
   expected outcome is `intent.status: unknown` (check it by reading the
   report).
4. **Clean controls:** merged commits with no later fix touching their files
   (`mine --clean` proposes them).

## Running

`evals.command` in `.review/config.yaml` is the headless review command. It
gets `{base} {head} {case_id} {out} {repo} {review_dir}` and must leave the
final `review.json` at `{out}`. The harness runs it inside a git worktree at
`head_sha` with `CODE_REVIEW_DIR` pointing at an isolated copy of `.review/`
(config, KB, flows, local catalog), so eval runs never touch real state.
Asynchronous agents are fine: the harness waits up to `evals.timeout_seconds`
for the file.

```bash
python3 <skill dir>/scripts/run_evals.py list
python3 <skill dir>/scripts/run_evals.py run --dry-run
python3 <skill dir>/scripts/run_evals.py run                      # all cases, evals.repeats times
python3 <skill dir>/scripts/run_evals.py run --cases a,b --repeats 1
python3 <skill dir>/scripts/run_evals.py run --baseline .review/evals/reports/<baseline>.json --gate
python3 <skill dir>/scripts/run_evals.py compare A.json B.json
```

For jj or Piper repositories, use `--checkout none`: the command then runs in
the live workspace and `collect_change.sh {base} {head}` diffs the revisions
without checking them out (levels 1+ then run against the working copy, so
keep eval depth at level 0–1 there).

The report gives catch rate, clean-control false-positive rate, findings per
PR, stability across repeats (mean Jaccard similarity of finding IDs), cost
per PR when the reviewer reports it, failed runs, and catch rate split by
`inverted`.

## The gate

No change to prompts, models, routing or KB ships if the catch rate drops or
clean-control false positives rise against the recorded baseline:

```bash
python3 <skill dir>/scripts/run_evals.py run --baseline <baseline.json> --gate   # exit 2 on regression
```

When a change passes, its report becomes the new baseline. Keep the baseline
path in the repo (a comment in `config.yaml` is enough).

Prove the gate works once: weaken the prompt deliberately (for example, remove
the "try to kill each candidate" paragraph or the catalog), run, and confirm
the report shows a measurable change. If it does not, the cases are too easy
or too few.

## Keep it live

Every bug that escapes to production becomes a case the same week. Bug types
shift as coding agents change, so the set must keep moving with them; a set
that is a year old measures last year's reviewer.

## Done when

- A baseline report exists under `.review/evals/reports/`.
- A deliberately weakened prompt shows a measurable drop against it.
- Sections 4 to 8 of the design each have at least one case or fixture:
  inverted vs not (split in the report), KB on vs off (files read), an
  off-spec intent case and a no-description case, the level 3 and level 4
  fixtures, and a cheaper-routing run that passes the gate.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
