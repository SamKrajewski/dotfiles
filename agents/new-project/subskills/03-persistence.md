# Step 3 — Persistence

**Goal:** decide what data outlives a run, where it lives, and how it is kept from being lost or destroyed.
**Writes:** `agents/03-persistence.md`
**Runs:** tiers M and L; tier S only if the Step 1 screening triggered it (ask only the ★ questions).

Data is the one thing a project cannot rebuild from source. Code bugs get fixed with a redeploy; a dropped table does not come back. So safety comes first in this step, ahead of convenience and speed.

## Questions

- ★ What must still exist after the program exits? List each kind of data.
- ★ Where does it write: which file system paths, database, object storage, or other service? Does it write anywhere else (caches, logs, queues, third-party APIs)?
- ★ What is it allowed to overwrite or delete, and how is a mistake undone?
- How much data, how fast does it grow, and how long is it kept?
- How is it read and written: mostly reads, heavy writes, transactions, search, analytics?
- How much loss is tolerable (minutes of data, hours)? How long may a restore take?
- Who owns the data? Is any of it sensitive? Must it be deletable on request?
- Where may it live: local disk, your own servers, a managed cloud service, a particular region?
- Is one data store enough? If more than one is proposed, what does each add that the first cannot do?

If the honest answer to the first question is "nothing", record that and stop. No store is the safest store.

## Recommend

Use `reference/defaults.md` § Databases and storage. The short version: one database until proven otherwise, PostgreSQL unless there is a reason, SQLite if everything lives on one machine, object storage for files.

## The data safety plan

Write each of these down as a decision. For the light form, only "File system" and "Destructive operations" usually apply.

**Schema and migrations** (any database)
- Name the migration tool. Migrations are numbered files in version control, applied in order.
- Never edit a migration that has been applied anywhere. Fix forward with a new one.
- Destructive changes go in three separate releases, **expand → migrate → contract**: add the new shape, move the data and switch the code, and only later remove the old shape.
- `DROP`, `TRUNCATE`, an unqualified `DELETE` or `UPDATE`, and narrowing a column each require a verified backup and the user's explicit approval for that statement.
- Test every migration from an empty database and from a production-like copy.
- State for each migration how it is reversed, or that it cannot be.
- Include the initial schema here as migration 0001.

**Backups**
- What is backed up, how often, where to, how long it is kept, and whether it is encrypted.
- A restore test on a schedule. A backup that has never been restored is not a backup.

**Environments and access**
- Separate databases and credentials for development, test and production.
- Development and test agents never hold production write credentials.
- The application's database role cannot drop or alter tables. A separate migration role can.

**Integrity**
- Constraints live in the database (`NOT NULL`, unique, foreign keys, checks), not only in code.
- Multi-step writes happen in a transaction. Operations that may be retried are idempotent.

**Deletion and retention**
- Soft delete or hard delete, per kind of data. How long deleted data stays recoverable.
- How long each kind of data is kept, and what removes it.

**File system**
- The exact directories the program may write to. Nothing outside them.
- Write to a temporary file and rename, so a crash never leaves a half-written file.
- Never overwrite or delete a user's file without a backup, a dry-run mode, or an explicit flag.

**Destructive operations**
- List every operation that deletes or overwrites data, and the guard on each: confirmation, dry run, soft delete, or backup first.

## Output template

```markdown
# 03 — Persistence
Status: APPROVED · <date> · approved by <user>

## What is stored       each kind of data: owner, sensitivity, volume, retention
## Where                each store: product, version, hosting, what it holds, why it was chosen
## Data model           entities, fields, relationships, constraints
## Migration policy     tool, rules, the expand → migrate → contract procedure
## Initial schema       migration 0001
## Backups and restore  schedule, location, retention, restore test
## Environments, access separate stores, roles and what each may do
## File system writes   allowed paths, write and cleanup rules
## Destructive operations  each one and its guard
```

## Done when

- Every kind of stored data has a home, an owner and a retention rule.
- Every destructive operation has a named guard.
- For a database: the migration policy and initial schema are written, and a restore test is planned.
- The user has approved it.

## Custom instructions

<!-- Add your own rules for this step below. They override the defaults above. -->
