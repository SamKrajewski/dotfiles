# Step 5 — Analyse: bug hunt, intent check, blast radius

**Goal:** produce the candidate findings, each traced and written up with
evidence, severity, confidence and a plain-language explanation. This is the
step that finds bugs; everything before it feeds it and everything after it
filters and formats.
**Writes:** `.review/tmp/draft.json` (first version; step 7 trims it).
**Runs:** every depth.

This file is the analysis prompt. The text between the prompt markers is the
only instruction the bug-hunting model gets, whether that model is you (read
the prompt and follow it with the inputs already in your context) or another
family's CLI (`scripts/build_prompt.py` fills the placeholders and writes
`tmp/prompt.md`). Tune the prompt here and only here; both paths change
together, and the evals (`subskills/evals.md`) are the gate on any edit.

## Running it

**In session** (routes `none`, `cross-family`, `blind-spot`):

1. Read `references/bug-catalog.md`, `.review/bug-catalog.local.md`,
   `references/nitpicks.md`, `references/explaining.md`, and the draft schema
   in `references/output.md`. The diff, intent and context pack are already in
   context from steps 1 to 4.
2. Follow the prompt below as written, treating each `{{placeholder}}` as the
   thing you already have.
3. Second pass (every route, `standard` and `deep` depth): after the full
   pass, run the bug hunt again restricted to `author.json.blind_spot_classes`,
   slowly, as if the first pass had missed them; when that list is empty, use
   `ai-artifacts` plus the two catalog classes most relevant to the changed
   files. Record the pass and its classes in `coverage.checked`.
4. Write the result to `tmp/draft.json`.

**Headless** (route `inverted-cli`, and the eval harness):

```bash
python3 <skill dir>/scripts/build_prompt.py              # -> tmp/prompt.md
python3 <skill dir>/scripts/build_prompt.py --incremental   # re-review: new commits only
# run author.json.reviewer_command with {prompt_file}=tmp/prompt.md and {out}=tmp/draft.json
python3 <skill dir>/scripts/review_report.py validate .review/tmp/draft.json
```

If the command fails or its output is not the schema, fall back to the
in-session blind-spot route and say so in `coverage.not_checked`.

**Budget:** `limits.budget_usd` for the depth (defaults 0.5 / 3 / 10). Hosts
rarely report spend in-session; use files read and minutes as the proxy
(`references/routing.md`). When it is spent, stop exploring, keep what is
traced, and list the rest under `not_checked`. Leave `cost` fields `null`
when unknown.

## Prompt

<!-- prompt:start -->
You are reviewing a code change for real bugs and for mismatches between what
was asked and what was built. You are not reviewing style, naming, structure,
or test coverage; another process handles those, and a comment about them here
costs more than it is worth because it buries the one comment that matters and
because coding agents turn every comment into extra code.

## The change

Branch `{{branch}}` at `{{head_sha}}`. Review depth: `{{depth}}`. Author
family: `{{author_family}}`. Blind-spot classes for this author family (give
them a second, slower pass): {{blind_spots}}.

Changed files:
{{changed_files}}

## Intent

{{intent}}

## Context pack

{{context_pack}}

## Diff

```diff
{{diff}}
```

## How to work

Work in three passes, then verify, then write. Do not skip a pass because the
diff looks simple; the bugs that matter are rare and look simple.

**Pass 1, bug hunt.** For every class in the catalog below, ask that class's
question of every hunk in the diff. Hunting a specific class is different from
reading the diff and waiting for something to feel wrong: you are checking a
list. For most classes on most hunks the honest answer is "nothing here"; move
on. When a hunk breaks an invariant from the context pack, that is a candidate
with the invariant as evidence. After the full pass, repeat the pass for the
blind-spot classes only.

**Pass 2, intent check.** Take each numbered requirement from the intent and
find the code that satisfies it. A requirement with no code, code that
contradicts a requirement or a documented decision, scope wider or narrower
than asked, or changes nothing in the intent explains are candidates. File
each under the most specific class that names the mechanism (a missing login
check is `auth-bypass`, not `intent-mismatch`) and record the requirement it
fails in the finding's `requirement` field; use `intent-mismatch` only when no
other class fits. If the intent is unknown, there is no mismatch to raise;
say `intent.status: unknown`.

**Pass 3, blast radius.** For every public symbol, schema, config key, event
or column the diff changes, use the consumer table in the context pack: which
consumers were updated, which were not, and what the un-updated ones now do.
Parallel sites that got one of several fixes are `incomplete-change`;
un-updated consumers are `contract-break`.

**Trace every candidate.** For each one, write the path from a concrete input
or state to the wrong outcome, with file and line at each hop. Assign
confidence honestly: `confirmed` only if it was reproduced, `traced` if every
hop is in the code, `suspected` otherwise (and only for critical or high).
Assign severity by consequence, not by how clever the bug is.

**Try to kill each candidate.** Look for the guard upstream, the schema
constraint, the test that already covers it, the reason the input cannot
occur. A candidate you cannot defend against your own best counter-argument is
dropped, not softened. One finding per root cause; list the other places
inside it.

**Write each survivor** with: the exact offending lines in `code` (verbatim,
short; this is what makes the finding's ID stable across runs), a
`failure_scenario` with its three parts (input or state, wrong outcome, who is
hurt), `evidence` naming what you read or ran, the smallest `suggested_fix`,
and an `explanation` written for a reader with no assumed expertise: define
the terms first, then number the steps with concrete values, then say who is
hurt. The explanation rules below are not optional.

**Be honest about coverage.** `coverage.checked` lists what you examined
(classes, invariants, consumers, commands run). `coverage.not_checked` lists
what you could not examine and why. No findings does not mean no bugs.

## Bug catalog

{{catalog}}

## Reporting rules

{{nitpicks}}

## Plain-language explanations

{{explaining}}

## Output

Return exactly one JSON object with this shape and nothing else, no prose
before or after it:

{{schema}}
<!-- prompt:end -->

## Done when

- `tmp/draft.json` exists, every finding has `code`, a three-part
  `failure_scenario`, `evidence`, and an `explanation` with concepts, steps
  and `why_it_matters`.
- `coverage.checked` names the passes you ran (including the blind-spot pass
  when routed) and `coverage.not_checked` is honest.
- `python3 <skill dir>/scripts/review_report.py validate .review/tmp/draft.json` passes.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
