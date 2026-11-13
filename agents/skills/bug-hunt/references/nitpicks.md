# Nitpicks, severity, confidence, caps

The one comment that matters gets buried under twenty that do not. Worse,
coding agents treat every review comment as an instruction, so a nitpick about
"consider adding validation" becomes a layer of defensive code nobody asked
for. The filter below exists to protect the signal.

## The reportability test

Report a finding only if all three can be written down concretely:

1. **The input or state** that triggers it ("a customer whose profile has not
   been created yet", "two requests within the same second").
2. **The wrong outcome** ("the handler throws", "the row is written twice").
3. **Who is affected** ("every new user on first login", "the on-call engineer
   who has to reconcile the ledger").

If any of the three is "might", "could", or "in theory", it is not a finding.
Either go and establish it (read the caller, run the test) or drop it.

## Never report

- Style, formatting, naming, import order, comment wording.
- "Consider adding" more validation, error handling, logging, or type
  annotations with no concrete failure that they would prevent.
- Missing comments or docstrings; missing tests as a general wish. (A test
  that was *weakened* to pass is a bug: `ai-artifacts`.)
- Refactoring taste: "this could be a separate function", "prefer composition".
- Performance remarks without a realistic size that makes them matter
  (`unbounded` needs a number).
- Problems in code the change did not touch, unless the change is what makes
  them reachable or wrong now.
- Anything already covered by a linter, type checker, or formatter that runs
  in CI.
- Duplicates: one finding per root cause, even if it shows in five places.
  List the places inside the one finding.

## Severity

| Severity | Meaning |
|---|---|
| `critical` | Outage, data loss or corruption, security breach, money moved wrongly, or a legal/privacy exposure. |
| `high` | Wrong behaviour on a common path: most users or most requests hit it. |
| `medium` | Wrong behaviour on an edge path, or an `intent-mismatch`. |

Nothing below `medium` is reported. If it is not at least wrong on an edge
path, it is a nitpick. A failed requirement that is also a bug of another
class (a missing login check is both `intent-mismatch` and `auth-bypass`) is
filed once, under the more specific class at that class's severity, with the
requirement it fails named in the finding's `requirement` field; the
`intent-mismatch` class and its `medium` cap are for mismatches no other
class covers.

## Confidence

| Confidence | Meaning |
|---|---|
| `confirmed` | Reproduced: a failing test, a request against the running app, a screenshot. |
| `traced` | Followed end to end in the code: input, path, wrong outcome, with file and line for each step. |
| `suspected` | Plausible but not traced. Allowed only for `critical` and `high`, and labelled as suspected in the report so the reader knows to verify it. |

A `medium` finding that is only `suspected` is dropped: the cost of a false
alarm on an edge case exceeds the value.

## Caps

- At most 8 findings per review (`limits.max_findings`). Over the cap, the
  most severe stay; the rest are listed as held back, not silently dropped.
- Minimal fixes only: the `suggested_fix` is the smallest change that removes
  the failure, not a redesign.
- One finding per root cause.

## Before the report, try to kill each finding

For every candidate, spend a moment arguing the other side: is there a guard
upstream, a constraint in the schema, a test that already covers it, a reason
the input cannot occur? If the argument wins, the finding goes. Record what you
checked in `coverage.checked`; it is useful to the reader either way.
