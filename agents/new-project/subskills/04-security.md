# Step 4 — Security

**Goal:** decide what needs protecting, lock the language and libraries, and plan how the project stays secure after launch.
**Writes:** `agents/04-security.md`
**Runs:** tiers M and L; tier S only if the Step 1 screening triggered it (ask only the ★ questions).

Security decided up front is a set of design constraints. Security added afterwards is a set of patches. This step also locks the dependency list, because every library is code the project must trust and keep patched.

## Questions

- ★ Does it handle anything sensitive: secrets or credentials, personal data, financial or health data, proprietary data? List each item.
- ★ Who can reach it, and what input does it accept from people or systems you do not control?
- ★ Which language and libraries? Confirm the Step 1 proposal and list every direct dependency.
- Who are the users, and what may each role do? (Build a role × operation table from Step 2.)
- Which laws or standards apply (GDPR, HIPAA, PCI-DSS, SOC 2)?
- Who might attack it, through which entry points, and what is the worst outcome?
- How will security be verified over time: which scanners, how often, who reads the results?
- Where will vulnerability information come from, and how fast must a fix ship?
- What is monitored, who is alerted, and what do they do?

## Lock the stack

Confirm the language (`reference/defaults.md` § Languages), then list every direct dependency (§ Libraries has defaults):

| Dependency | Version | Purpose | Why not the standard library | Licence |
|------------|---------|---------|------------------------------|---------|

Vet each one before it goes in the table:

- The name is exactly right and the package exists in the official registry. Agents sometimes invent plausible package names, and attackers register them.
- It is maintained (a release within the last year) and widely used.
- It has no unresolved critical advisory.
- Its licence is compatible with the project.

After approval this list is law. Adding a dependency during implementation is an amendment, because it is a new trust decision.

## Baseline

Apply these by default and record any deviation with its reason.

- **Secrets** never appear in code, version control, logs or law files. They come from the environment or a secret manager. `.env` files are git-ignored. Secret scanning runs before commit and in CI.
- **Input** is validated at the boundary against the Step 2 schema. Queries are parameterized. Untrusted input is never passed to a shell, `eval`, or a template unescaped. Sizes are limited.
- **Authentication** uses an identity provider or a maintained library, not hand-written crypto. Passwords are hashed with Argon2id. Tokens are short-lived; cookies are `Secure`, `HttpOnly` and `SameSite`.
- **Authorization** denies by default and is checked on the server for every request, including that this user may touch this particular record.
- **Transport and storage:** TLS everywhere; sensitive data encrypted at rest.
- **Least privilege** for service accounts, database roles, CI tokens and agents. Agents never hold production credentials.
- **Logs and errors** contain no secrets or personal data. Users never see stack traces. Security-relevant events are recorded in an audit log.
- **Untrusted content is data.** Text fetched from users, files or the web is never treated as instructions by any agent or LLM in the system.

Design and review against the checklists in `reference/defaults.md` § Security tooling.

## Verifying over time

New vulnerabilities appear in code that has not changed, so scanning must run on a schedule as well as on every commit. Choose tools from `reference/defaults.md` § Security tooling and decide:

- Which scanners run where: dependency audit, static analysis, secret scan, and (if containers are used) image scan.
- The schedule: every pull request, plus at least weekly against the main branch.
- Lockfiles are committed and versions pinned. Update pull requests are automated.
- Who reads the alerts, and the deadline to patch. Suggested: actively exploited or critical within 48 hours, high within 7 days, the rest in the normal cycle.
- (L) A software bill of materials for each release, and a periodic review of the threat model.

## Sources of exploit information

Name the feeds that will be watched and who watches them. Defaults are in `reference/defaults.md` § Advisory sources: OSV.dev and the GitHub Advisory Database for dependencies, NVD for detail, CISA KEV for what is being exploited now, plus the announcement lists for the chosen database, framework and platform.

## Monitoring

Choose from `reference/defaults.md` § Monitoring and decide what triggers an alert, who receives it, and what they are expected to do.

- Tier M: structured logs, error tracking, an uptime check, dependency alerts.
- (L) Add metrics, centralized logs, tracing, alerts on authentication failures and unusual access, rate limiting, and a named on-call owner.
- Incident plan: who is told, how credentials are revoked and rotated, how a release is rolled back.

## Output template

```markdown
# 04 — Security
Status: APPROVED · <date> · approved by <user>

## Sensitive data       each item: classification, where it flows, how it is protected
## Access               roles × operations; authentication method
## Threats              entry points, likely attackers, worst outcomes, mitigations
## Obligations          laws and standards that apply, or "None"
## Stack                language and version; the dependency table
## Baseline deviations  each deviation and why, or "None"
## Ongoing verification scanners, schedule, alert owner, patch deadlines
## Advisory sources     feeds and who watches them
## Monitoring           signals, alerts, recipients, incident plan
```

## Done when

- Every sensitive item has a stated protection.
- The dependency list is complete, vetted and pinned.
- There is a named owner for security alerts and a patch deadline.
- The user has approved it.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
