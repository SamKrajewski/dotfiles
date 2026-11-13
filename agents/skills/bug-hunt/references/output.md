# Output: files, schemas, stable IDs, state

Everything the pipeline produces lives under the review directory
(`.review/` in the repo, or `$CODE_REVIEW_DIR`). `tmp/` and `state/` are
gitignored; `config.yaml`, `kb/`, `flows.yaml`, `bug-catalog.local.md` and
`evals/` are meant to be committed so the whole team shares them.

```
.review/
  config.yaml              per-repo settings (templates/config.yaml)
  kb/INDEX.md, kb/*.md     knowledge base (references/context.md)
  flows.yaml               user flows for browser testing
  bug-catalog.local.md     repo-specific bug classes
  evals/cases/<id>/case.yaml, evals/reports/
  state/<branch>.json      prior findings per branch; state/dismissed.json
  tmp/change.json          step 1 output (collect_change.sh)
  tmp/author.json          step 2 output (detect_author.py)
  tmp/intent.md            step 3 output (written by the agent)
  tmp/context.md           step 4 output: the context pack
  tmp/prompt.md            headless prompt (build_prompt.py), when used
  tmp/draft.json           step 5–7 output: the draft the agent writes
  tmp/review.json, tmp/review.md   step 8 output (review_report.py finalize)
```

## change.json (step 1)

Produced by `scripts/collect_change.sh`. Key fields: `vcs`, `branch`,
`base_sha`, `head_sha` (suffixed `+dirty-<hash>` for an uncommitted worktree),
`changed_files[]` with `status`, `additions`, `deletions`, `skipped` (reason or
null), `diff` (skipped files removed), `commits[]` with `trailers`, `pr`
(from `gh`, else null), `triage` (`suggested`, `floor`, `depth`, `reasons`),
`prior` (last state for this branch) and `rereview` (`unchanged`, or the
incremental `commits` and `diff` since the prior head).

## draft.json (what the agent writes before finalize)

The analysis step produces candidate findings; the filter step trims them;
the result is one JSON object. `review_report.py finalize` adds the IDs, merges
prior state, applies the caps and writes the final files. Keep the shape
exactly; the validator rejects missing explanations and suspected `medium`
findings.

<!-- draft-schema:start -->
```json
{
  "reviewer_model": "name of the model that did step 5, or '' for the host agent",
  "inverted": false,
  "depth": "light|standard|deep",
  "intent": {
    "statement": "3-5 lines: what the change is meant to do, in the author's terms",
    "sources": ["PR body", "issue #123", "docs/adr/007.md"],
    "status": "met|partial|not_met|unknown"
  },
  "findings": [
    {
      "class": "a class from the bug catalog, e.g. async-race",
      "requirement": "optional: the intent requirement this finding fails, e.g. 'R2'; set when a finding of any class covers a failed requirement",
      "severity": "critical|high|medium",
      "confidence": "confirmed|traced|suspected",
      "file": "path relative to the repo root",
      "lines": [88, 104],
      "title": "one line, the wrong outcome first: 'Retry can charge a customer twice'",
      "code": "the offending lines, verbatim (used for the stable ID; keep it short)",
      "failure_scenario": "input or state -> wrong outcome -> who is hurt",
      "evidence": "what you read or ran that establishes it, with file:line for each hop",
      "suggested_fix": "the smallest change that removes the failure",
      "explanation": {
        "concepts": [{"term": "retry", "meaning": "trying the same action again when the first try seemed to fail"}],
        "steps": ["plain sentence with a concrete value", "next step", "..."],
        "why_it_matters": "who is hurt, in plain words"
      },
      "verified_by": "optional: 'level 2 test <path>' or 'level 3: GET /orders/7 as user B returned 200'"
    }
  ],
  "coverage": {
    "checked": ["what was examined or run, e.g. 'callers of getUser (3 sites)', 'npm test on 12 files'"],
    "not_checked": ["what was skipped and why, e.g. 'UI at phone size: no browser tool'"],
    "runtime_level": 0,
    "files_read": 0,
    "kb_entries": ["names of knowledge-base entries used"]
  },
  "kb_updates": [{"entry": "billing", "proposal": "document that charge() now requires an idempotency key"}],
  "cost": {"usd": null, "tokens": null, "wall_seconds": null}
}
```
<!-- draft-schema:end -->

`cost` fields are `null` when the host reports nothing; an in-session agent
usually knows only `wall_seconds`. A headless reviewer (model inversion,
evals) must print exactly this object and nothing else;
`review_report.py validate <file>` checks it.

## review.json (final)

`finalize` adds: `schema`, `generated_at`, `repo_root`, `branch`, `base_sha`,
`head_sha`, `author_family`, each finding's `id`, `omitted_findings[]` (over
the cap), and `prior_findings[]` with `status` `resolved | still-present |
dismissed`. `review.md` is the human rendering: a one-line verdict, a small
table, intent, findings (technical and plain-language sections), coverage,
prior findings, proposed knowledge-base edits.

## Stable IDs

`id = sha256(class + "\n" + file + "\n" + code-with-all-whitespace-removed)[:12]`

Line numbers are deliberately not part of the hash, so a finding keeps its ID
when code above it moves. Two runs on the same SHA produce the same IDs as
long as `class`, `file` and the quoted `code` are the same, which is why `code`
must be the verbatim offending lines and not a paraphrase. Compute one by hand
with `review_report.py id --class C --file F --code "..."`.

## State and re-review

- `state/<branch>.json` records the findings of the last run (IDs, files,
  titles) and a short history. `collect_change.sh` reads it and, when the
  prior head is an ancestor of the new head, adds `rereview.diff` covering only
  the new commits.
- On a re-review, analyse the new commits, then re-check each prior finding
  against the current code and report its status. Never re-raise a dismissed
  one.
- `review_report.py dismiss <id> --reason "..."` records a dismissal in
  `state/dismissed.json` (global, because IDs are branch-independent).
- An unchanged head (`rereview.unchanged: true`) should produce the same IDs
  and nothing new. If it does not, the finding was not stable; fix the
  `code` snippet or the class.

## Posting to a code host (optional)

Only when the user asks. Tag each comment with its finding ID in a hidden
marker (`<!-- bug-hunt:id=abc123def456 -->`) so a later run can update the
comment instead of adding a duplicate. With `gh`: `gh pr review --comment -b
"$(cat .review/tmp/review.md)"`, or one inline comment per finding via `gh api
repos/{owner}/{repo}/pulls/{n}/comments`.
