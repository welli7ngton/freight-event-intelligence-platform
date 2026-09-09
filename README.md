# Freight Event Intelligence Platform

An event-driven backend for receiving and processing freight-shipment lifecycle
events. The project is a Python modular monolith used to explore DDD, layered
architecture, persistence, and a future move toward asynchronous processing.

## Current status

The domain, application layer, SQLAlchemy persistence, Alembic migrations, and
FastAPI API are implemented. Phase 2.5 validated persistence against a real,
isolated PostgreSQL database. Phase 2.6 reproduced the current concurrent
idempotency limitation and documented the chosen Phase 3 strategy.

Implemented capabilities include:

- `Shipment`, immutable `ShipmentEvent`s, lifecycle state machine, and event
  handler;
- idempotency by `event_id`, including PostgreSQL unique-key conflict recovery
  for concurrent duplicate delivery;
- durable out-of-order event classification: valid late events remain in history
  without regressing the current shipment projection;
- PostgreSQL repositories behind application ports;
- atomic creation of a shipment and its historical `SHIPMENT_CREATED` event;
- FastAPI endpoints for shipments and operational events;
- isolated PostgreSQL integration tests, including constraints, rollback, HTTP
  flow, and concurrent duplicate-event reproduction.

RabbitMQ publishing and an ingestion worker are implemented. The worker uses
bounded retries and preserves terminal failures in a dead-letter queue.
Transactional outbox and observability are not implemented yet.

## Architecture

```text
app/
├── api/                  # FastAPI routes, schemas, and dependencies
├── application/          # Use cases and repository ports
├── domain/               # Entities, events, and business rules
├── infra/database/       # SQLAlchemy models, mappers, repositories, session
└── workers/              # Reserved for future asynchronous processing

alembic/                  # Database migrations
tests/                    # Unit and integration tests
```

The domain does not depend on FastAPI, SQLAlchemy, or PostgreSQL. The
application layer orchestrates use cases through ports; infrastructure provides
their implementations.

## Requirements

- Python 3.12 or later
- Docker Desktop with Docker Compose
- PostgreSQL, either local or supplied by Compose
- RabbitMQ, supplied by Compose for asynchronous event ingestion

## Local setup

In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env-example .env
```

Configure `.env` with the credentials and URLs for the target environment. It
is ignored by Git; `.env-example` documents every required setting without
containing a usable secret.

Start PostgreSQL and apply migrations:

```powershell
task setup
```

`DATABASE_URL` is used by the API and Alembic. PostgreSQL container credentials
and the isolated test database URL are also configured through `.env`. Use a
different `.env` per environment, supplied by that environment's secrets
mechanism in staging and production.

## Run the API

```powershell
task api
```

The API is available at `http://127.0.0.1:8000`.

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health check: `GET /health`

## Endpoints

### Create a shipment

```http
POST /shipments
Content-Type: application/json
```

```json
{
  "reference_number": "SHIP-001",
  "origin": "Fortaleza",
  "destination": "Sao Paulo",
  "carrier": "Carrier A"
}
```

`POST /shipments` is the only public creation API. `CreateShipment` creates a
shipment in `CREATED` and records a `SHIPMENT_CREATED` event with
`source = platform` in the same SQLAlchemy session. Repositories do not commit;
`get_db()` commits at the end of a successful request and rolls back on error.

### Get a shipment

```http
GET /shipments/{shipment_id}
```

Returns `404` when the shipment does not exist.

### Get shipment events

```http
GET /shipments/{shipment_id}/events
```

Returns the event history ordered by `occurred_at`.

### Receive an event

```http
POST /events
Content-Type: application/json
```

```json
{
  "event_id": "11111111-1111-1111-1111-111111111111",
  "shipment_id": "22222222-2222-2222-2222-222222222222",
  "event_type": "PICKUP_SCHEDULED",
  "source": "carrier_api",
  "occurred_at": "2026-09-06T12:00:00Z",
  "payload": {}
}
```

This endpoint accepts operational lifecycle events for an existing shipment.
`SHIPMENT_CREATED` is rejected with `422`; it is historical creation metadata,
not a state-machine transition. `LOCATION_UPDATED` requires numeric `latitude`
and `longitude` values in `payload`. Invalid transitions return `409`; an
unknown shipment returns `404`.

## Shipment states

```text
CREATED --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--> DELIVERED
DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED --DELIVERED--> DELIVERED
```

The domain uses `occurred_at` to update `updated_at` when an event changes
state or location. `received_at` records when the platform received the event.

### Out-of-order events

Every valid event is retained in shipment history. `processing_status` is
`APPLIED` when it updates the current projection and `STORED_OUT_OF_ORDER` when
it is retained only as historical evidence. Location and lifecycle timelines
are evaluated independently: late locations cannot overwrite newer coordinates,
and late lifecycle events cannot move current status backward. This domain
policy is independent of Kafka and will be reused by a future worker.

## Tests and quality

```powershell
task test-fast          # concise unit-test output
task test               # default suite; integration tests are excluded
task test-api           # API-layer tests
task test-integration   # isolated PostgreSQL integration tests
task lint               # Ruff lint
task lint-fix           # apply Ruff lint fixes
task format             # format with Ruff
task format-check       # check formatting
task check              # formatting, lint, and tests
task compile            # compile app and tests
```

Run the following before submitting a change:

```powershell
task check
```

### Integration tests

Integration tests exclusively use `freight_events_test` in the `postgres-test`
service on port `5433`; they never use the development database. Start the
service and run the tests as follows:

```powershell
docker compose up -d postgres-test
task test-integration
```

Set `TEST_DATABASE_URL` to use another test URL. For safety, it must point to a
database named exactly `freight_events_test`.

## Database and migrations

```powershell
task db-up          # start PostgreSQL
task db-down        # stop services
task db-logs        # follow PostgreSQL logs
task db-migrate     # apply migrations
task db-rollback    # roll back one migration
task db-current     # show current revision
task db-history     # show migration history
task db-revision -- "description" # create an autogenerated migration
task broker-up       # start RabbitMQ
task broker-down     # stop RabbitMQ
task worker          # run the shipment-event ingestion worker
```

Always review autogenerated migrations before applying them.

## RabbitMQ worker

RabbitMQ uses the `freight.shipment-events` topic exchange and the versioned
`shipment.event.received.v1` routing key. The worker validates the message and
calls `ReceiveShipmentEvent`; it contains no shipment business rules. The API
remains synchronous and does not publish automatically yet: reliable
post-commit publication requires the Transactional Outbox planned for Phase 6.

Retryable processing failures are sent to a retry queue and return to the main
queue after `RABBITMQ_RETRY_DELAY_MS`. After `RABBITMQ_MAX_ATTEMPTS`, or for
invalid messages and business-rule failures, the original message is stored in
the dead-letter queue with attempt and failure metadata.

Start the broker and worker with:

```powershell
task broker-up
task worker
```

## Decisions and documentation

Architecture decisions are recorded in [app/docs/adr](app/docs/adr):

- [ADR-001 — Shipment Core Domain and State Machine](app/docs/adr/001-Shipment-Core-Domain-and-State-Machine.md)
- [ADR-002 — Phase 2 API and Persistence Evolution](app/docs/adr/002-Phase-2-API-and-Persistence-Evolution.md)
- [ADR-003 — Atomic Shipment and SHIPMENT_CREATED Persistence](app/docs/adr/003-Atomic-Shipment-and-SHIPMENT_CREATED-Persistence.md)
- [ADR-004 — Concurrent Idempotency Strategy](app/docs/adr/004-Concurrent-Idempotency-Strategy.md)
- [ADR-005 — Out-of-Order Event Treatment](app/docs/adr/005-Out-of-Order-Event-Treatment.md)
- [ADR-006 — RabbitMQ Asynchronous Ingestion](app/docs/adr/006-RabbitMQ-Asynchronous-Ingestion.md)
- [ADR-007 — RabbitMQ Failure Recovery](app/docs/adr/007-RabbitMQ-Failure-Recovery.md)

## Next steps

1. Implement Phase 3A: turn a concurrent unique-constraint conflict into a
   defined idempotent API outcome.
2. Add Transactional Outbox before publishing accepted API events.
