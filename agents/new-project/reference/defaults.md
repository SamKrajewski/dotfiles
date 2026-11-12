# Defaults

Baked-in recommendations for the planning steps. They are starting points: the user's stated preference wins, an existing team stack usually wins, and otherwise recommend from here with a one-line reason. Edit this file to change what agents recommend.

Tools move. Before locking anything in, check that it is still maintained and that the package name is exactly right.

**Contents:** Languages · Libraries · Databases and storage · Build and isolation · Where to run it · Security tooling · Advisory sources · Monitoring · Subagent models

## Languages

Choose in this order: what the user and their team can read and maintain, then what has the best libraries for the problem, then raw speed (only when there is a measured need).

| Language | Reach for it when | Cost |
|----------|-------------------|------|
| Python | Scripts, automation, data work, ML, quick APIs. Default for tier S. | Slow for CPU-heavy work. Needs type hints and a type checker to keep a contract honest. |
| TypeScript | Anything in a browser; Node services; front and back end sharing types | Large dependency trees. Types vanish at runtime, so validate at the boundary. |
| Go | Network services, CLIs, infrastructure tools. Easy concurrency, one static binary. | Verbose, few abstractions |
| Rust | Performance- or memory-critical code, systems work, WebAssembly | Slowest to write. Low-power models struggle with it, so expect more `complex` functions. |
| Java / Kotlin | Large back ends in a JVM shop; Android | Heavier runtime and tooling |
| C# | .NET shops, Windows, Unity | Tied to the .NET ecosystem |
| Swift | Apple platforms | Little use elsewhere |
| Bash | Under about 50 lines of gluing commands together | Fragile beyond that. Switch to Python. |
| SQL | The data already lives in a database: do the work there | — |
| C / C++ | Only when something requires it: existing code, hardware, a kernel | Memory safety is on you |

Statically typed languages let the contract be compiled before any function body exists (Step 7). For tiers M and L that deserves real weight.

## Libraries

Standard library first. Every dependency is code you did not write, must keep patched, and must trust. Add one when it removes real work or real risk (parsing, crypto, database drivers), not for convenience.

| Need | Python | TypeScript | Go | Rust |
|------|--------|------------|----|------|
| HTTP API | FastAPI | Fastify, Hono | net/http + chi | axum |
| HTTP client | httpx (urllib if trivial) | fetch (built in) | net/http | reqwest |
| Validation | pydantic | zod | go-playground/validator | serde + validator |
| CLI | argparse (stdlib), typer | commander | flag (stdlib), cobra | clap |
| Database access | SQLAlchemy, psycopg | Drizzle, Prisma, pg | database/sql + pgx, sqlc | sqlx |
| Migrations | Alembic | Drizzle Kit, Prisma Migrate | golang-migrate, goose | sqlx-cli, refinery |
| Tabular data | csv/json (stdlib) when small; pandas or polars | — | encoding/csv | csv, polars |
| Tests | pytest, hypothesis | vitest | testing (stdlib) | cargo test, proptest |
| Lint and format | ruff | biome, or eslint + prettier | gofmt, golangci-lint | rustfmt, clippy |
| Type check | pyright or mypy | tsc --strict | compiler | compiler |
| Contract docs to HTML | Sphinx, pdoc | TypeDoc | go doc, pkgsite | rustdoc |
| Password hashing | argon2-cffi | @node-rs/argon2 | x/crypto/argon2 | argon2 |
| Dependency audit | pip-audit | npm audit | govulncheck | cargo audit, cargo deny |

Other languages: Javadoc (Java), Dokka (Kotlin), DocFX (C#), Doxygen (C/C++) for contract docs.

Cross-language test tools: Schemathesis (fuzz an API against its OpenAPI file), Playwright (browser end-to-end), k6 (load), Testcontainers (real databases in tests).

## Databases and storage

One database until proven otherwise. PostgreSQL unless there is a reason. SQLite if everything lives on one machine.

| Need | Default | Good at | Watch out for |
|------|---------|---------|---------------|
| A few small records, one writer | Plain files (JSON, CSV, TOML) | Simple, human-readable, no setup | Partial writes and concurrent writers. Write to a temp file, then rename. |
| Single-user or embedded app | SQLite | Zero administration, transactions, one file to back up | One writer at a time; one host only |
| General application data | PostgreSQL | Integrity, transactions, JSONB, full-text search, extensions (pgvector, PostGIS, TimescaleDB) | Needs operating, or a managed service |
| Existing MySQL shop | MySQL / MariaDB | Mature, widely hosted | Fewer features than Postgres; stay only for compatibility |
| Cache, sessions, rate limits | Redis or Valkey | Sub-millisecond reads, expiry, pub/sub | Not a system of record. Assume it can be wiped. |
| Truly schema-free documents | MongoDB | Flexible nested documents, horizontal scale | Most "schema-free" data is relational. Try Postgres JSONB first. |
| Files, images, backups, blobs | S3-compatible object storage (S3, R2, MinIO) | Cheap, durable, effectively unlimited | Keep keys and metadata in the database, not blobs in the database |
| Analytics on local files | DuckDB + Parquet | Fast columnar queries in-process | Not for many concurrent writers |
| Analytics at scale | ClickHouse, BigQuery, Snowflake | Billions of rows | Cost and operations; a second system to keep in sync |
| Search | Postgres full-text first; Meilisearch or OpenSearch when outgrown | Relevance ranking, typo tolerance | Search index is a copy. The database stays the source of truth. |
| Vector search | pgvector first; Qdrant at scale | Embedding similarity | Same: a derived index |
| Queues and events | A Postgres table (`SKIP LOCKED`) first; NATS, Kafka or Redpanda when outgrown | Decoupling, retries, fan-out | Delivery is at-least-once. Handlers must tolerate duplicates. |

## Build and isolation

| Language | Build and packaging | Isolation and locking |
|----------|---------------------|-----------------------|
| Python | uv with `pyproject.toml` (single scripts: inline dependencies, PEP 723) | virtualenv + `uv.lock` |
| TypeScript | pnpm or npm; tsc, vite or esbuild | lockfile; `npm ci` / `pnpm install --frozen-lockfile` |
| Go | `go build` | `go.mod` + `go.sum` |
| Rust | cargo | `Cargo.lock` |
| Java / Kotlin | Gradle (or Maven) | dependency locking and verification |
| C / C++ | CMake + vcpkg or Conan | pinned manifests |
| Any, as task runner | just or make | — |

Commit the lockfile. Keep runtime dependencies separate from development and test dependencies, and ship only the runtime set.

## Where to run it

Choose the lowest rung that meets the requirements. Each rung up buys capability and costs operations.

1. **Run it directly** — a script or single binary, started by hand, cron or a systemd unit. Right for tier S and many tier M tools.
2. **One container** — when it needs system packages or must behave identically elsewhere. Multi-stage build, non-root user, slim pinned base image.
3. **Docker Compose on one machine** — an app plus its database, cache or worker. Also the default local development setup.
4. **Managed platform** — Cloud Run, Fly.io, Render, Railway, ECS/Fargate, or serverless functions. No servers to patch; scaling included.
5. **Kubernetes** — only when several services need independent scaling or rolling deploys across machines *and* someone will operate it. Prefer managed (GKE, EKS, AKS), or k3s on your own hardware. "Probably not" is the default answer.

Infrastructure as code for tier L: OpenTofu/Terraform or Pulumi. CI/CD: whatever hosts the repository (GitHub Actions, GitLab CI, Forgejo Actions).

## Security tooling

| Job | Tools |
|-----|-------|
| Dependency vulnerabilities | OSV-Scanner (any language) plus the per-language audit tool above; Dependabot or Renovate for update PRs |
| Static analysis | Semgrep, CodeQL; Bandit (Python), gosec (Go) |
| Secret scanning | gitleaks or TruffleHog, in pre-commit and in CI |
| Containers and infrastructure | Trivy or Grype (images), hadolint (Dockerfiles), Checkov (Terraform, Kubernetes) |
| Bill of materials (L) | Syft, producing CycloneDX or SPDX |
| Running application | OWASP ZAP; Schemathesis for APIs |

Checklists to design and review against: OWASP Top 10, OWASP API Security Top 10, OWASP ASVS, CWE Top 25.

## Advisory sources

- **OSV.dev** — aggregated open-source advisories. First stop, and what OSV-Scanner reads.
- **GitHub Advisory Database** — feeds Dependabot.
- **NVD** — CVE details and severity scores.
- **CISA KEV** — vulnerabilities being exploited right now. Patch these first.
- **Ecosystem databases** — PyPA Advisory Database, RustSec, Go Vulnerability Database, npm advisories.
- **Vendor announcement lists** for the chosen database, framework, operating system and cloud provider.

## Monitoring

| Need | Default |
|------|---------|
| Errors | Sentry, or self-hosted GlitchTip |
| Uptime | An external check (Uptime Kuma or a hosted pinger) |
| Logs | Structured JSON to stdout, collected by the platform; Loki or the cloud's log service for tier L |
| Metrics | Prometheus + Grafana, or the cloud provider's equivalent |
| Tracing (L) | OpenTelemetry |
| Alerts | Routed to a named human, not a dashboard nobody opens |

## Subagent models

| Role | Model class | Examples |
|------|-------------|----------|
| Planning and orchestration (Steps 1–7) | Strongest available | — |
| Implement a `standard` function | Low-power | Haiku, Gemini 3.0 Flash |
| Implement a `complex` function | Mid-low | Sonnet, Gemini 3.8 Flash |
| Write tests from the contract | Mid-low | Sonnet, Gemini 3.8 Flash |
| Review the contract | Strongest available from a different vendor than the author | GPT if Claude wrote it, Claude if GPT wrote it |

Tests get a mid-low model because they are the check on the low-power implementers: a weak test suite removes the safety net that makes cheap implementation acceptable.

## Custom instructions

<!-- Add your own preferences below: house languages, approved or banned libraries, standard infrastructure, model names. They override the tables above. -->
