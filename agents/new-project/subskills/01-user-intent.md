# Step 1 — User Intent

**Goal:** understand what the user actually wants, well enough to size the project and decide which later steps run.
**Writes:** `agents/01-user-intent.md`
**Runs:** always.

Everything downstream inherits from this step. A misunderstanding here is copied into every later document, so ask more questions than feels natural, scaled to the size of the project.

## 1. Listen, then restate

Let the user describe the project in their own words. Restate it in two or three sentences and have them correct you before asking anything else.

## 2. Core questions (every project)

Skip any the user has already answered.

1. What does it do, in one sentence? What problem does that solve?
2. Who or what uses it: you, a team, the public, another program?
3. What does "done" look like? Ask for one concrete example of a successful use.
4. Where will it run: your machine, a server, the cloud, a browser, a device?
5. Is it a one-off, or will it be maintained? For how long?
6. What is out of scope? Non-goals stop agents from building extras.
7. Constraints: language or stack preferences, deadline, budget, performance, licences, anything that must or must not be used.
8. First-party tools (section 5). Always ask this one.

## 3. Assign a tier

| Tier | Looks like | Question budget |
|------|------------|-----------------|
| **S — Script** | One file or a small CLI. Run on demand, by one person. Nothing long-lived. | The core questions, about 3–6 in total |
| **M — Application** | Multi-file program, library, or one service. Some state, some users. | Core plus the M list, about 8–15 |
| **L — System** | Several services or databases, real users, sensitive data, or uptime expectations | Core plus M plus L, 15 or more over several rounds |

Tell the user which tier you chose and why, and let them overrule it. If the project sits between two tiers, ask. Signs to move up a tier: other people's data, money, more than one deployable, or anything that must stay running.

## 4. Deeper questions

**Tier M and L**

- Who are the users and roles? What can each do?
- How much: users, requests, data volume, growth over a year?
- Which outside systems does it talk to? Who owns them?
- Is there a user interface? What kind, and on which platforms?
- What should happen when something fails: retry, report, stop?
- What must be configurable, and by whom?
- Who maintains it after launch?

**Tier L only**

- How does it split into services, and why does each one exist?
- Availability and latency targets? What does an outage cost?
- Legal or regulatory obligations (GDPR, HIPAA, PCI-DSS, SOC 2)? Data residency?
- Single tenant or multi-tenant?
- Existing infrastructure, accounts and standards it must fit into?
- Infrastructure budget ceiling?
- How will it be rolled out: all at once, or staged?

## 5. First-party tools

Ask explicitly: **"What first-party or internal tools, data and services can this project use?"** Examples: an internal image database, a company API, a shared design system, an existing auth service, a private package registry, a data warehouse.

For each one, record:

| Field | What to capture |
|-------|-----------------|
| Name and purpose | What it is and what it holds or does |
| Interface | MCP server, CLI, API with a spec, SDK, or file path, and where its documentation lives |
| Authentication | How access is granted and where credentials come from. Never the secret itself. |
| Permissions | Read or write; which parts |
| Environments | May agents call it during development and tests, or production only? Is there a sandbox? |
| Limits | Rate limits, quotas, cost per call |
| Sensitivity | What kind of data comes back |
| Working example | One real call and its response |
| Owner | Who to ask when it breaks |

Agent-usable interfaces are strongly preferred (an MCP server, a documented CLI, an API with a machine-readable spec) because implementation and test agents can then use the tool directly. If a resource only has a human interface, ask whether building a wrapper is in scope.

With the user's permission, run one read-only example call now. Broken access is far cheaper to find here than in Step 8.

## 6. Propose the stack

Recommend a language from `reference/defaults.md` § Languages with a one-line reason, and ask about known library preferences or exclusions. If Step 4 will run, this is a proposal that Step 4 locks in. If Step 4 is skipped, it is locked here.

## 7. Screening questions and the step plan

Steps 1, 2, 7 and 8 always run. For tiers M and L, so do the rest. For tier S, these questions decide:

| Step | Runs when |
|------|-----------|
| 3 Persistence | It changes or deletes existing data, or keeps state between runs: a database, files it rewrites, remote state. Writing a fresh output file that Step 2 already describes does not count. |
| 4 Security | It handles secrets or personal, financial or health data; is reachable over a network; or accepts input from anyone other than the user |
| 5 Testing | Someone else depends on it, or it runs unattended. Otherwise the contract tests in Step 8 are enough. |
| 6 Deployment | It runs anywhere other than the machine it is written on, or someone else installs it |
| 9 Final steps | Step 6 runs |

Write the plan as a table: each step, then **run**, **light**, or **skipped — reason**.

## Output template

```markdown
# 01 — User Intent
Status: APPROVED · <date> · approved by <user>

## Summary             3–5 sentences, in the user's words where possible
## Users and usage     who uses it, how often, at what scale
## Success criteria    observable and checkable
## Non-goals
## Constraints
## First-party tools   one table per tool, or "None"
## Stack               language and reason; preferences and exclusions
## Tier and step plan  the tier, why, and the step table
## Assumptions         everything inferred, each confirmed by the user
```

## Done when

- The user has confirmed the summary, the tier and the step plan.
- The first-party tools question was asked and answered, even if the answer is "none".
- Every assumption is confirmed. Nothing is marked "TBD".

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
