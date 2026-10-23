# ADR-001: Modular monolith with a separate worker, and the approved MVP stack

- **Status:** Proposed. Awaiting owner acceptance at the P0.1 review.
- **Date:** 2026-10-23
- **Source:** `docs/HERMECIOUS_EXECUTION_BLUEPRINT_v1.md` §1 (Technical baseline) and §11 (Initial ADR log)

## Context

Hermecious is a self-hosted, single-organization sales operations product. One operator runs it on one private VPS. Its correctness depends on transactional guarantees that cross several concerns, such as consent and suppression checks, idempotent sends, owner locks and audit trails. Splitting those concerns across network boundaries would add failure modes such as partial commits, dual writes and distributed retries. A one-operator deployment gains nothing from that split.

## Decision

1. **Architecture.** Hermecious is a modular monolith. It has a single FastAPI application and a single background worker. The worker runs as a separate process but shares the same codebase and database. There are no microservices.
2. **Runtime boundaries.** Requests flow `web UI -> FastAPI -> domain application services -> PostgreSQL`. Application services enqueue jobs atomically with domain transactions through a transactional outbox. The worker dispatches those jobs and is the only caller of source, model and messaging adapters. Provider callbacks go through a verified webhook receiver, which stores a durable inbound event for the inbox processor.
3. **AI authority boundary.** The LLM cannot write database records or send messages. It returns strictly typed recommendations. Deterministic application policy decides every state transition and authorizes every external side effect.
4. **Module layout.** Modules live under `apps/api/app/{api,auth,core,domain,services,adapters,persistence,workers}` and `apps/web/`. A directory is created only by the subphase that first puts code in it. Empty architecture is never scaffolded.
5. **Approved MVP stack:**

   | Layer | Choice |
   |---|---|
   | UI | Next.js + TypeScript |
   | API | Python FastAPI + Pydantic |
   | Persistence | PostgreSQL + SQLAlchemy 2 + Alembic (PostgreSQL is the system of record) |
   | Background | Redis + one Python worker library: Dramatiq **or** RQ, chosen by a later ADR |
   | AI | Provider-neutral ModelGateway (Ollama/local or an authorized hosted model), schema-checked outputs |
   | Data retrieval | Allowed source adapters with rights metadata; optional self-hosted SearXNG |
   | Messaging | Official WhatsApp Business Platform adapter; simulator first |
   | Auth | Session-based admin auth, Argon2id, secure cookies |
   | Operations | Docker Compose + reverse proxy with HTTPS on one VPS |
   | Tests | pytest, mypy, ruff, Playwright, Vitest, contract fixtures |

6. **Explicitly excluded until a new ADR justifies them:** Qdrant, Neo4j, Kafka, Kubernetes, multi-agent chat swarms, a browser automation farm, distributed workflow orchestration, microservices, vector search and RAG. PostgreSQL full-text search is the default for the offer catalog.

## Consequences

- Domain invariants such as suppression, ownership and idempotency can be enforced in a single database transaction.
- One deployable plus one worker keeps operations within reach of a single operator on one VPS.
- The API and worker scale together. That is acceptable at pilot volume. Revisit this only when measurements show contention.
- Module boundaries hold by convention and review, not by process isolation, so code review must reject cross-module shortcuts.

## Open decisions (not decided by this ADR)

- Worker library choice (Dramatiq vs RQ): needs its own ADR before the worker is built (P0.2).
- ADR-002 to ADR-008 in blueprint §11 are not yet written or accepted.

## Rollback

This ADR adds documentation only. To revert it, mark the status `Superseded` with a link to the replacement ADR. Do not delete it.
