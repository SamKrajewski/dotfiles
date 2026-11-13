---
subsystem: {subsystem}
paths: ["src/{subsystem}/**"]
last_verified_sha: {sha}
---

## How it works

Two to five sentences. What this subsystem is for, and the one thing a
reviewer most often gets wrong about it.

## Key flows

```
request -> middleware/session -> handler -> store
```

## Files and entry points

- `src/{subsystem}/index.ts` — public API
- `src/{subsystem}/store.ts` — persistence; every write goes through `commit()`

## Invariants

Write each as a sentence a reviewer can check a hunk against. These produce
the best findings.

- Every `/api/admin/*` handler calls `requireAdmin` before touching the store.
- Amounts are integers in minor units; no floats cross this boundary.

## Consumers

- `src/web/...` calls `createSession`
- Other repos or services that depend on this contract, and how they would break.

## Past incidents

- {date}: {one line: what broke, root cause, bug class}
