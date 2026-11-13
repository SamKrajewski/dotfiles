# Step 6 — Deployment

**Goal:** decide how the project is built, where it runs, how changes reach it safely, and write the exact commands to do it.
**Writes:** `agents/06-deployment.md`
**Runs:** tiers M and L; tier S only if the Step 1 screening triggered it (ask only the ★ questions).

Deployment is where Steps 3–5 meet: the data stores, the security controls and the test gates all have to exist somewhere real. Reread those three files first, and make sure every decision in them has a place in this one.

In Step 7 every decision in this file becomes a devops task, and in Step 8 a fresh-context agent on a strong model executes each task with the relevant section quoted verbatim as its specification. So write every section as something that can be executed without asking: exact tools, exact names, exact commands, and what the result should look like.

## Questions

- ★ What exactly does it run on: hardware, operating system, CPU architecture, memory, GPU? Who owns and operates that?
- ★ How does it get there, and how is it started, updated and rolled back?
- ★ Which version control system and host? Who may merge?
- Which build system? How are dependencies isolated and locked?
- Does it need containers? Does it need Kubernetes?
- Is there a CI/CD pipeline? On which platform? What must pass before a merge, and before a release?
- Which environments does a change pass through on its way to production?
- How is it exposed: ports, domain, TLS, firewall?
- How much downtime is acceptable during a deploy? How quickly must a rollback complete?
- What is the monthly cost ceiling?

## Recommend

**Build and dependency separation.** Use `reference/defaults.md` § Build and isolation. Commit the lockfile, keep runtime dependencies apart from development and test ones, and give each service its own dependency set.

**Where it runs.** Use `reference/defaults.md` § Where to run it and pick the lowest rung that meets the requirements:

- Tier S: run it directly. No container.
- Containers: yes when it is deployed to a server, needs system packages, or must behave identically across machines.
- Kubernetes: only when several services need independent scaling or rolling deploys across machines, and someone will operate the cluster. Otherwise no.

**Version control and safe pull requests.** Git, with short-lived branches off a protected `main`:

- No direct pushes to `main`. Every change arrives by pull request with CI passing.
- Review before merge: a human for tier L; for a solo project, an independent review agent plus the user's spot checks.
- `CODEOWNERS` assigns `agents/` and `docs/ARCHITECTURE.md` to the user, so any pull request that touches law needs their approval.
- Small pull requests: one contract component each.
- Agents never force-push, never merge their own work past the gate, and never bypass a failing check.

**CI/CD.**

- On every pull request: format, lint, type check, build, tests, dependency audit, secret scan, static analysis, and `sha256sum -c agents/MANIFEST.sha256` to prove the law is intact.
- Build once and promote the same artifact through each environment. Do not rebuild for production.
- Migrations run as their own gated step, before the application is updated.
- A production deploy is followed by a health check and rolls back automatically if it fails. (L) It also needs a human approval.
- Releases are tagged with a version.

**Security in deployment** (from Step 4).

- Deploy credentials are least-privilege and short-lived (OIDC to the cloud instead of stored keys).
- Third-party CI actions and base images are pinned by digest.
- Containers run as a non-root user; images are scanned.
- Only the needed ports are open. TLS terminates in front of everything public.
- Secrets are injected at run time, never baked into an image.
- Backups from Step 3 are working before the first real data arrives.

## The runbook

Write the exact, copy-and-paste commands, numbered, with the expected result after each. Use a named placeholder only for a value that does not exist yet, such as `<version>`.

1. Build
2. First deploy, from nothing
3. Routine deploy
4. Rollback
5. Restore from backup
6. Where to look: logs, health check, dashboards

Step 8.5 rehearses this runbook and Step 9 follows it to the letter, each as a devops task whose brief quotes it, so a wrong command here is a defect in a law file. Have the user check anything that depends on their accounts or machines.

## Output template

```markdown
# 06 — Deployment
Status: APPROVED · <date> · approved by <user>

## Target               hardware, OS, architecture, hosting, operator, cost ceiling
## Build                build system, lockfile, runtime vs. development dependencies
## Packaging            direct, container or orchestrated, with the reason
## Version control      host, branch rules, review rules, CODEOWNERS
## CI/CD                platform; checks per pull request; release pipeline
## Environments         the path a change takes to production
## Network and secrets  exposure, TLS, how secrets are supplied
## Runbook              the six procedures above, as exact commands
```

## Done when

- Every data store from Step 3, control from Step 4 and test gate from Step 5 has a place in this plan.
- The runbook has exact commands for build, deploy, rollback and restore.
- The user has approved it.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
