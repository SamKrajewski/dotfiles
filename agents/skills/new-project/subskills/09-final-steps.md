# Step 9 — Final Steps

**Goal:** follow the deployment guide, make the service available, and hand it over.
**Writes:** `agents/09-final-steps.md` (the release record)
**Runs:** when Step 6 ran. Tier S projects without a deployment finish at the end of Step 8.

Nothing new happens here. Every command was written in Step 6 and rehearsed in Step 8.5, so this step should be uneventful. An error at this point is not a bug to fix on the spot. It means an earlier step missed something, and that is what needs finding.

## Before deploying

Confirm each of these, and stop if any is false:

- The user gave a go at the end of Step 8.5, and says go again now.
- `law.sh verify` passes (run from the project root: `bash <this skill's directory>/scripts/law.sh verify`).
- CI is green on the exact commit being released.
- Backups are configured and a restore has been tested.
- The rollback procedure was rehearsed.
- Monitoring and alerts are live and reach a named person.

Deploying to production is outward-facing and hard to undo. Do not start without the user's explicit go for this release.

## Deploy

The production deploy is the last devops task in the PRD. Run it through the orchestrator (`orchestrator.md`): a fresh strong-class agent whose brief quotes the runbook, started only after the user's go for that task id. Or the user runs the runbook by hand. Either way:

1. Follow the runbook in `06-deployment.md` exactly, one command at a time.
2. After each command, compare the result with the expected result written in the runbook.
3. Record each command and its outcome for the release record.

Do not improvise, substitute or "improve" a command. If the runbook is wrong, stop.

## Verify

- Health checks pass.
- Smoke tests pass: the read-only fixtures, run against production.
- Dashboards and logs look as they did in staging. No errors, no secrets in logs.
- The first backup completes.

## Make it available

- Point the domain, confirm TLS, and open access to the intended users.
- Hand over: a README covering what it is, how to run and operate it, where the logs and dashboards are, who is alerted, and how to roll back.
- Tell the user it is live and what to watch during the first day.

## If anything goes wrong

1. **Stop.** Do not debug in production.
2. **Roll back** using the runbook, and confirm the previous state is healthy.
3. **Tell the user** what happened and what state things are in now.
4. **Find the gap.** Write a short account: what failed, which step should have caught it, and what was missing from which law file.
5. **Go back through the pipeline.** A contract or runbook defect is an amendment (`amend.md`). Then repeat Steps 8.3–8.5 before trying again.

## Release record template

```markdown
# 09 — Final Steps
Status: RELEASED · <version> · <date> · go given by <user>

## Release            version, commit, artifact digest, PRD version
## Commands run       each runbook command and its result
## Verification       health, smoke tests, monitoring, first backup
## Access             where it lives and who can reach it
## Known limitations
## Rollback           how to return to the previous version from here
## Incidents          what went wrong and the gap behind it, or "None"
```

After the user accepts the release, run `law.sh seal` to seal the record.

Later changes go through `add-feature.md`.

## Done when

- The service is reachable by its intended users and every verification passed.
- The release record is written and sealed.
- The user has what they need to operate it.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
