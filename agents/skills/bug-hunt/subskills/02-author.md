# Step 2 — Detect the author, pick the reviewer

**Goal:** know whether a human or a coding agent wrote the change, which
family, and therefore which model reviews it and whether a blind-spot pass is
needed.
**Writes:** `.review/tmp/author.json`.
**Runs:** `standard` and `deep`. For `light`, run the script (it is cheap) but
do not pursue inversion.

## Run it

```bash
python3 <skill dir>/scripts/detect_author.py            # reads tmp/change.json
python3 <skill dir>/scripts/detect_author.py --family claude   # the user told you who wrote it
```

The output has `family`, `confidence`, the `signals` that led there, and the
routing decision: `route`, `inverted`, `reviewer_family`, `reviewer_command`,
`blind_spot_classes`. The detection order and the fingerprint table are in
`references/inversion.md`; add a row there when an agent-written change comes
back `unknown`, instead of guessing.

Two rules that are easy to break:

- **Never infer the author from code style.** The detector only looks at
  labels, commit text, branch names, logins, emails and the registry. If the
  user asks who wrote it, answer from `signals` or say the signals are absent.
- **Set `inversion.self_family`** in `.review/config.yaml` to the family of
  the agent running this skill (a Gemini-based host is `gemini`, Claude Code
  is `claude`, Codex is `gpt`). Blank means the router cannot tell same-family
  from cross-family and falls back to the blind-spot pass every time.

## What the route means for step 5

The route decides which model runs step 5 and the `inverted` flag. The
blind-spot second pass is not route-dependent: at `standard` and `deep` depth
step 5 always repeats the hunt over the author family's weak classes
(`blind_spot_classes`; when the family has none documented, `ai-artifacts`
plus the two catalog classes most relevant to the changed files). It is
cheap, and the skews are documented per author family, not per reviewer.

| `route` | Step 5 |
|---|---|
| `none` | Human or unknown author. Current model. `inverted: false`. |
| `cross-family` | Author family differs from the reviewer already. Current model. `inverted: true`. |
| `inverted-cli` | Same family, and a different-family command is configured. Step 5 builds the prompt file and runs that command headless; its JSON is the candidate list. `inverted: true`, `reviewer_model` = that CLI's model. |
| `blind-spot` | Same family (or self unknown), no other model available. Current model; the second pass is the only mitigation, so do not skip it. `inverted: false`. |

The talk's figures (about 10% more bugs caught when inverted; Claude code
skews to off-by-one, GPT code to auth bypass) are claims to verify: the eval
report splits catch rate by `inverted`.

## Done when

- `tmp/author.json` exists and you can state in one line: author family,
  confidence, route.
- You know the values of `reviewer_model` (the name of the model doing step
  5: your own model name if you know it, the CLI's model for `inverted-cli`,
  else `""`) and `inverted` that will go into the draft.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
