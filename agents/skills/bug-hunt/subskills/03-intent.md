# Step 3 — State the intent

**Goal:** write down what the change is supposed to do, where that is
established, and the concrete requirements the analysis will check the code
against. Code can be bug-free and still wrong; a one-line request to an agent
leaves a lot to guess, and the guesses are where intent mismatches live.
**Writes:** `.review/tmp/intent.md`.
**Runs:** every depth. For `light`, one line from the commit subject is enough.

## Sources, in order

1. **The change itself:** PR title and body, commit subjects and bodies
   (`change.json.pr`, `change.json.commits`). Quote, do not paraphrase.
2. **Linked tickets:** issue references in that text (`#123`, `Fixes …`,
   `JIRA-123`, `b/123456`, a tracker URL). Fetch them with whatever connector
   exists: `gh issue view`, a Jira or Linear CLI, the Buganizer CLI inside
   Google. `context.tickets` in config names the tracker. No connector: say
   the ticket was not read.
3. **Docs and decisions:** files under `context.docs` (`docs/`, `adr/`,
   `README.md`) that mention the feature, endpoint or module being changed.
   Read the one or two that match; do not survey the whole folder.
4. **The user**, when present and the above is empty: ask one question, "What
   should this change do?" Their answer is a source ("user, in conversation").

## Write the statement

`tmp/intent.md`:

```markdown
# Intent

<3 to 5 lines in the author's own terms: what the change does, for whom,
and any constraint stated (performance, compatibility, rollout).>

Sources: PR #412 body; issue #398; docs/adr/007-webhooks.md

## Requirements to check
1. Retries failed webhooks up to 3 times.            (issue #398)
2. Backoff between retries.                            (issue #398)
3. No change to the webhook timeout.                   (ADR 007 fixes it at 10s)

## Out of scope / unexpected in the diff
- Changes to `config/timeouts.yaml` are not mentioned anywhere.
```

Requirements are the checklist step 5 runs the intent check against; write
them as testable sentences with their source. "Unexpected in the diff" is
where bundled unrelated changes are caught.

## When there is nothing

If no source states an intent (no description, no ticket, no doc, no user),
write:

```markdown
# Intent
No stated intent was found (no PR body, commit bodies, linked tickets or docs).
Status: unknown
```

and set `intent.status: unknown` in the draft. Do not invent an intent from
the code; an invented intent is always "met" and hides the mismatch the step
exists to find.

## Done when

- `tmp/intent.md` has a statement with sources and a numbered requirements
  list, or an explicit `unknown`.
- Anything in the diff that no source explains is listed under "unexpected".

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
