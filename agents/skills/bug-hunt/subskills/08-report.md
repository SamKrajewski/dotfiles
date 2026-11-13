# Step 8 — Report and save state

**Goal:** produce `review.json` and `review.md`, with stable finding IDs and
the status of prior findings, present the result honestly, and save the state
so the next run on this branch updates instead of repeating.
**Writes:** `.review/tmp/review.json`, `.review/tmp/review.md`,
`.review/state/<branch>.json`.
**Runs:** every depth.

## Finalize

```bash
python3 <skill dir>/scripts/review_report.py finalize .review/tmp/draft.json
```

This computes each finding's ID (`sha256(class + file + whitespace-free
code)[:12]`, so line shifts do not change it), removes dismissed findings,
marks prior findings `resolved` / `still-present` / `dismissed`, sorts and
caps, validates, renders the markdown, and writes the state. Fix anything it
rejects in the draft rather than editing `review.json` by hand; the state must
match the report.

## Present it

Read `tmp/review.md` and give the user:

1. **The verdict line first.** Findings count by severity, intent status,
   runtime level, whether the reviewer was inverted. If the cap held back
   `high` findings, say so here.
2. **Findings in order**, each with the technical fields and the
   plain-language section. Keep the two visibly separate so an expert can skip
   the plain section and anyone else can skip the technical one. The
   plain-language rules are in `references/explaining.md`; do not assume the
   reader's expertise.
3. **Prior findings** with status changes, on re-reviews.
4. **Coverage**, always: what was checked and what was not, with the runtime
   level. No findings is reported as "no findings that pass the
   reportability test, with these things unchecked", never as "looks good".
5. **Knowledge base changes** (entries written this run, edits proposed in
   `kb_updates`) and setup gaps (no test command, no start script,
   `self_family` unset, unanswered setup questions) as a short list the user
   can act on.

Do not post to GitHub, Critique, or any code host unless the user asks. When
they do, use the finding IDs as hidden markers in each comment so a re-run can
update rather than duplicate (see `references/output.md`).

## Dismissals and follow-ups

- The user says a finding is wrong or accepted: `python3 <skill
  dir>/scripts/review_report.py dismiss <id> --reason "..."`. It will never be
  raised again on any branch.
- A finding turns out to be a real escaped bug later, or the user says one
  was missed: add it as an eval case (`subskills/evals.md`). The eval set is
  what keeps the reviewer honest over time.
- The user wants fixes applied: fix only the findings they name, with the
  minimal fix, and re-run from step 1 afterwards; the re-review will mark
  them resolved.

## Done when

- `review.json` validates, `review.md` is written, and the state file for the
  branch is updated.
- The user has the verdict line, the findings with both descriptions, and the
  coverage list.
- Running the pipeline again on the same head would raise nothing new and
  reproduce the same IDs.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
