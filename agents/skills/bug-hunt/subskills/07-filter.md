# Step 7 — Filter hard

**Goal:** cut the candidate list down to the findings that pass the
reportability test, at the right severity and confidence, one per root cause,
within the cap. The value of the review is decided here as much as in the
hunt: every nitpick that survives dilutes the real finding and will be
"fixed" by the next coding agent that reads the review.
**Writes:** the final `.review/tmp/draft.json`.
**Runs:** every depth.

The rules are in `references/nitpicks.md`. This step applies them, in order,
to every candidate.

## The gate, per candidate

1. **Reportability.** Can you write the input or state, the wrong outcome, and
   who is affected, each concretely? If any is "might" or "in theory", drop
   it. (You may go back and establish it, if budget remains.)
2. **Never-report list.** Style, naming, "consider adding", missing comments
   or tests as a wish, refactor taste, untouched code the change did not make
   wrong, anything a linter or type checker already enforces: drop.
3. **Severity.** `critical` (outage, data loss, security, money), `high`
   (wrong on a common path), `medium` (wrong on an edge path, or
   `intent-mismatch`). Below medium: drop.
4. **Confidence.** `confirmed` requires a reproduction from step 6. `traced`
   requires every hop in the code with file and line in `evidence`.
   `suspected` is allowed only for critical/high and is labelled. A
   `suspected` medium is dropped.
5. **One per root cause.** Merge duplicates; list the other locations inside
   the surviving finding.
6. **Minimal fix.** Cut `suggested_fix` to the smallest change that removes
   the failure. No redesigns.
7. **Plain language.** The `explanation` meets the checklist in
   `references/explaining.md`: terms defined before use, numbered steps with
   concrete values, harm stated. Rewrite it if it reads like the evidence
   field.
8. **Stable `code`.** The `code` field is the verbatim offending lines, not a
   paraphrase; the finding ID is derived from it.

## Intent status

Set `intent.status` now: `met` (every requirement has code and nothing
unexplained was bundled), `partial` (some requirements met, or unexplained
changes present), `not_met` (the core requirement is missing or
contradicted), `unknown` (no stated intent). Every failed requirement must be
covered by exactly one finding: if the failure is also a bug of a more
specific class, that finding carries it (set its `requirement` field, keep
its own class and severity); only a failure no other class covers becomes an
`intent-mismatch` finding. Do not file the same root cause twice to satisfy
this rule.

## Re-reviews

For each prior finding (`change.json.prior`), check the current code: fixed
(it will be marked `resolved` by finalize when its ID is absent) or still
present (keep it in the draft with the same `class`, `file` and `code` so the
ID matches). Do not re-argue dismissed findings; finalize removes them.

## Cap

`limits.max_findings` (default 8). Keep the most severe; finalize lists the
rest as held back. If you are at the cap with mediums left over, that is
expected; if you are at the cap with highs left over, say so prominently in
the report's first line.

## Validate

```bash
python3 <skill dir>/scripts/review_report.py validate .review/tmp/draft.json
```

Fix every error it prints (missing explanation steps, missing `code`, a
suspected medium) before step 8.

## Done when

- Every remaining finding passes all eight checks and `validate` is clean.
- `intent.status` is set and justified.
- `coverage.checked` records the counter-arguments you tested; dropping a
  candidate after checking is useful information for the reader.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
