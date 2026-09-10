# Agent instructions

## Role and collaboration

Act as a Senior Software Engineer and help the user develop Python backends and strengthen their understanding of
software architecture, design patterns, Clean Code, and advanced Python idioms.

- Explain why each proposed architectural change, pattern, or refactoring fits
  the problem, which complexity it resolves, and its costs or limitations.
- Focus on structural decisions, testability, coupling, and business invariants;
  skip basic syntax tutorials. Discuss SOLID, DDD, dependency injection,
  protocols, dataclasses, or other patterns when relevant to the actual change.
- Keep a professional, encouraging, peer-to-peer tone. Ask guiding questions
  when a meaningful design choice benefits from discussion, while progressing
  with work already authorized by the user.
- Prefer a small, concrete solution over abstractions introduced only for
  hypothetical future requirements.

## Documentation and source of truth

Read the relevant documentation and inspect the implementation before changing
behavior. This file applies throughout the repository.

- [README.md](README.md): project overview, HTTP examples, and local workflows.
- [Technical context](app/docs/context.md): current capabilities and boundaries.
- [ADR-001](app/docs/adr/001-Shipment-Core-Domain-and-State-Machine.md): domain
  independence and the explicit state machine.
- [ADR-002](app/docs/adr/002-Phase-2-API-and-Persistence-Evolution.md): API,
  application ports, and persistence boundaries.
- [ADR-003](app/docs/adr/003-Atomic-Shipment-and-SHIPMENT_CREATED-Persistence.md):
  atomic shipment creation and its historical event.
- [ADR-004](app/docs/adr/004-Concurrent-Idempotency-Strategy.md): event identity
  constraints and concurrent conflict recovery.
- [ADR-005](app/docs/adr/005-Out-of-Order-Event-Treatment.md): independent
  lifecycle/location timelines and durable late-event classification.
- [ADR-006](app/docs/adr/006-RabbitMQ-Asynchronous-Ingestion.md): RabbitMQ
  ingestion and the synchronous HTTP contract.
- [ADR-007](app/docs/adr/007-RabbitMQ-Failure-Recovery.md): retries and DLQ.
- `pyproject.toml`, `.env.example`, `docker-compose.yml`, and `alembic/`:
  executable configuration, dependencies, commands, and schema evolution.

Documentation records current behavior alongside the historical context of ADRs.
Verify behavior against code and tests; preserve accepted decisions unless a
change is justified. Later ADRs refine earlier decisions. Current capabilities
extend through Phase 5, with Phase 6 Transactional Outbox planned. Do not treat
a phase label as proof of complete production guarantees or test coverage.
Use dated validation in `app/docs/context.md` and rerun relevant checks.

## Project and architecture

This is an event-driven freight backend implemented as a Python modular monolith.
The stack is Python 3.12+, FastAPI/Pydantic, synchronous SQLAlchemy 2 with psycopg,
PostgreSQL 17, Alembic, and RabbitMQ with Pika. Development tools are pytest,
Ruff, and taskipy; dependency versions are defined in `pyproject.toml`.

| Location | Responsibility |
| --- | --- |
| `app/domain/shipment/` | Entities, immutable events, state machine, business rules, exceptions, and late-event policy |
| `app/application/use_cases/` | Orchestrate business operations through injected ports |
| `app/application/ports/` | `Protocol` contracts for repositories and publishing |
| `app/application/messaging/` | Versioned transport message contract and serialization |
| `app/api/` | HTTP schemas, DTO conversion, routes, error translation, and dependency assembly |
| `app/infra/database/` | ORM models, mappers, repositories, engine, and sessions |
| `app/infra/messaging/` | RabbitMQ publishing/consumption, topology, and failure classification |
| `app/workers/` | Worker entry points and transaction orchestration |
| `alembic/versions/` | Database migrations |
| `tests/` | Domain, application, API, infrastructure, and integration tests |

Keep the domain independent of FastAPI, SQLAlchemy, PostgreSQL, and RabbitMQ.
Application use cases depend on ports, and infrastructure implements them.
This allows business rules to run unchanged from HTTP and worker adapters and
to be tested with in-memory repositories. The cost is explicit mapping and
dependency assembly; reuse the existing boundaries instead of adding parallel
abstractions. Controllers, repositories, and workers must not absorb business
rules. Keep domain handlers free of external side effects.

## Business and persistence contracts

- `Shipment` is a mutable dataclass created in `CREATED`. `ShipmentEvent` uses
  `frozen=True, slots=True`; preserve historical facts and event identity.
- `POST /shipments` is the only public creation contract. `CreateShipment`
  creates the shipment and `SHIPMENT_CREATED` event with `source = platform`
  in one transaction. The event's `occurred_at` equals shipment `created_at`.
- `SHIPMENT_CREATED` is historical metadata, not a state transition. Both the
  ingestion use case and handler reject it; `POST /events` returns 422.
- Preserve the lifecycle table:

  ```text
  CREATED --PICKUP_SCHEDULED--> SCHEDULED
  SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
  PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
  IN_TRANSIT --DELAY_DETECTED--> DELAYED
  IN_TRANSIT --DELIVERED--> DELIVERED
  DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
  DELAYED --DELIVERED--> DELIVERED
  ```

- `LOCATION_UPDATED` requires latitude and longitude and does not change status.
  Validate transport inputs and preserve domain payload normalization.
- Distinguish `occurred_at` from `received_at`. Domain changes use occurrence
  time; generated application timestamps use UTC.
- The handler compares location events against `last_location_at` and lifecycle
  events against `last_lifecycle_at`. Strictly older events are retained as
  `STORED_OUT_OF_ORDER` without altering that projection; otherwise processing
  uses the normal update/transition rules and records `APPLIED`. These clocks
  are independent. Do not add replay or assume a global monotonic `updated_at`.
- `shipments` holds the current projection; `shipment_events` holds history,
  ordered by `occurred_at` on retrieval. Preserve JSONB payload mapping, the
  event foreign key, unique shipment reference, and event primary key.
- Repositories do not commit. Request repositories share the session supplied
  by `get_db()` in `app/api/dependencies.py`, which commits success, rolls back
  exceptions, and closes the session. Preserve atomic state/event writes.
- `event_id` is the deduplication identity. The sequential existence check is
  an optimization; PostgreSQL's `shipment_events` primary key is the final
  uniqueness guarantee. The HTTP route flushes, recognizes specifically
  `shipment_events_pkey` conflicts, rolls back, and reloads persisted state.
  Do not treat every `IntegrityError` as a duplicate or assume the worker has
  identical conflict recovery. Duplicate identity protection does not establish
  general serialization of distinct events for one shipment.
- Keep the HTTP contract synchronous: `POST /events` returns the shipment with
  200, missing shipments map to 404, and invalid transitions map to 409.
  Preserve health and shipment/history query endpoints.

## Messaging and future work

- Use the versioned `shipment.event.received.v1` contract through the durable
  `freight.shipment-events` topic exchange. Preserve deterministic serialization,
  contract validation, event/shipment identity, timestamps, source, and payload.
  `message_id` is distinct from the business deduplication key `event_id`.
- Workers reuse `ReceiveShipmentEvent` and ACK successful processing only after
  the database transaction commits.
- Keep failure classification centralized. Invalid messages and business failures
  go directly to the DLQ; operational database failures, timeouts, OS errors,
  and unknown exceptions receive bounded retries.
- Retry queue TTL controls delay. `RABBITMQ_MAX_ATTEMPTS` counts total attempts
  (default three). Preserve the original body and attempt/failure headers.
  Current code ACKs failed deliveries after the retry/DLQ publish call returns.
  Publisher confirms and mandatory routing are absent; do not describe this as
  confirmed durable delivery. Preserve commit-before-ACK in worker callbacks.
- Delivery is not exactly once. A publish/ACK interruption can cause redelivery;
  maintain idempotency and test relevant failure paths.
- The HTTP API does not automatically publish accepted events. Transactional
  Outbox is planned to make publication intent atomic with database changes.
  Write an ADR before implementing it; account for recovery and duplicate
  publication. Do not add an unprotected database-commit/broker-publish flow.
- Redis, structured logging, Prometheus, Grafana, full replay, and dedicated
  `processed_events`/`outbox_events` tables are not current capabilities.
  Introduce future infrastructure only for an explicit requirement. Avoid
  premature microservices, Kafka, Kubernetes, full CQRS, or Event Sourcing.

## Local development

Use PowerShell from the repository root. Reuse `.venv` when available. For a
fresh environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
# Only when .env does not already exist:
Copy-Item .env.example .env
```

Configure environment-specific values without committing `.env` or credentials.
`DATABASE_URL` configures application persistence and Alembic. If activation is
unavailable, invoke executables from `.venv\Scripts\` directly.

| Command | Purpose |
| --- | --- |
| `task setup` | Start development PostgreSQL and apply migrations |
| `task api` | Start FastAPI with reload at `http://127.0.0.1:8000` |
| `task broker-up` | Start RabbitMQ |
| `task worker` | Run the ingestion worker |
| `task db-migrate` | Apply migrations through head |
| `task db-current` / `task db-history` | Inspect migrations |
| `task db-revision -- "description"` | Generate a migration for review |
| `task db-rollback` | Roll back one migration; changes database state |
| `task db-down` | Run Compose down, stopping all Compose services |
| `task broker-down` | Stop RabbitMQ |

Review autogenerated migrations before applying them. Schema changes should
include the necessary ORM, mapper, and migration updates; do not recreate tables
as a substitute for schema evolution.

## Testing and quality

- Follow Ruff configuration: Python 3.12, 88-character line length, double
  quotes, space indentation, and configured import/lint rules. Use type hints
  and existing `Protocol`/dataclass conventions at application boundaries.
- Use `tests/factories/` and in-memory repositories for domain/application tests.
  Keep default tests independent of running PostgreSQL and RabbitMQ services.
- Add or update behavioral tests for functional changes and relevant failures.
  Use real PostgreSQL integration tests for constraints, transaction rollback,
  and concurrency; mocks or SQLite cannot establish those PostgreSQL guarantees.
- `task test`, `task test-fast`, and `task test-api` exclude integration tests
  by default. `task test-integration` selects the integration marker, including
  PostgreSQL and/or RabbitMQ tests.
- Integration fixtures apply migrations and clean tables. Never target the
  development database: `TEST_DATABASE_URL` must name exactly
  `freight_events_test`, normally served by `postgres-test` on port 5433.
  Supply the test URL in the process environment before pytest starts; check
  `tests/conftest.py` rather than assuming `.env` is loaded early enough.
  Broker integration tests use `TEST_RABBITMQ_URL` and isolated test queues.

```powershell
task check          # Ruff formatting check, lint, and default tests
task compile        # Compile app and tests
# When integration coverage is relevant:
docker compose up -d postgres-test rabbitmq
task test-integration
```

Run `task check` before submitting code changes, plus integration checks relevant
to the behavior changed. For documentation-only edits, verify accuracy, local
links, commands, and whitespace without starting services unnecessarily.
Report checks actually executed, failures, and unavailable prerequisites;
never present historical results as fresh validation.

## Delivery workflow

Inspect the current code and relevant ADRs, identify the smallest useful change,
implement it, test at the appropriate level, and update affected documentation.
When implementing the roadmap, work one phase at a time and validate the current
phase before advancing. Reproduce concurrency problems before choosing fixes.

Preserve unrelated work. Avoid broad refactors without a functional or
architectural reason. Record material architectural decisions with context,
alternatives, trade-offs, and consequences in `app/docs/adr/`; use the next
available number.
Update `app/docs/context.md` for capability changes and README for user-facing
setup or contract changes. Finish by explaining what changed, why, what was
validated, and any relevant limitation or next step within the requested scope.
