# Freight Event Intelligence Platform

An event-driven backend for receiving and processing freight-shipment lifecycle
events. The project is a Python modular monolith used to explore DDD, layered
architecture, persistence, and asynchronous processing through RabbitMQ.

## Current status

The domain, application layer, SQLAlchemy persistence, Alembic migrations,
FastAPI API, RabbitMQ ingestion, bounded retry/DLQ handling, Transactional Outbox,
and Phase 7 observability are implemented. See
[technical context](app/docs/context.md) for behavior, validation, and limitations.

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
Recorded events also create an atomic outbox intent. A separate relay publishes
confirmed notifications. JSON logs, correlation IDs, Prometheus metrics and an
optional Grafana dashboard support operation across the three processes.

## Architecture

```text
app/
├── api/                  # FastAPI routes, schemas, and dependencies
├── application/          # Use cases and repository ports
├── domain/               # Entities, events, and business rules
├── infra/                # Database, RabbitMQ adapters, and configuration
└── workers/              # RabbitMQ ingestion entry point

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
# Only if .env does not already exist:
Copy-Item .env.example .env
```

Configure `.env` with the credentials and URLs for the target environment. It
is ignored by Git; `.env.example` contains local example values to replace.
`DATABASE_URL` and `RABBITMQ_URL` are required by their respective adapters;
application configuration loads `.env` using python-dotenv.

### Recommended local workflow

Run these commands from the repository root. Keep the API, workers, and tests
in separate terminals when they need to run at the same time:

```powershell
# Starts the application PostgreSQL container and applies Alembic migrations.
task setup

# Start the API.
task api

# In another terminal, start RabbitMQ and the ingestion worker when testing
# asynchronous ingestion.
task broker-up
task worker

# In another terminal, start the transactional outbox relay when testing
# recorded-event notifications.
task outbox-worker
```

`task setup` is equivalent to `task db-up` followed by `task db-migrate`.
`DATABASE_URL` is used by the API and Alembic. PostgreSQL container credentials
and the isolated test database URL are configured through `.env`. Use a
different `.env` per environment, supplied by that environment's secrets
mechanism in staging and production.

To see every available task and its command:

```powershell
task --list
```

### Build and run the API image

Build the production image from the repository root:

```powershell
docker build --tag freight-event-intelligence-platform:local .
```

The image runs the API as a non-root user on port `8000` and includes a
container health check for `/health`. Start PostgreSQL and RabbitMQ first:

```powershell
task setup
task broker-up
```

When those services run on the host, use `host.docker.internal` in the
container's connection URLs. The `.env` file normally uses `localhost`, which
would refer to the API container itself:

```powershell
docker run --rm --name freight-api `
  --env-file .env `
  -e DATABASE_URL="postgresql+psycopg://postgres:change-me@host.docker.internal:5432/freight_events" `
  -e RABBITMQ_URL="amqp://guest:guest@host.docker.internal:5672/%2F" `
  -p 8000:8000 `
  freight-event-intelligence-platform:local
```

Check the running container with `http://127.0.0.1:8000/health`. The image is
intended for the API process; run ingestion and outbox workers as separate
containers from the same image with their respective task commands or module
entry points.

## Run the API

```powershell
task api
```

The API is available at `http://127.0.0.1:8000`.

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health check: `GET /health`

The health endpoint returns a static response; it does not check database or
broker readiness.

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

Returns the event history ordered by `occurred_at`, including each event's
`processing_status`. An unknown shipment ID returns an empty list.

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

This endpoint processes operational lifecycle events synchronously for an existing
shipment and returns its projection with HTTP 200. Its transaction also records
an outbound notification intent; the separate relay publishes it to RabbitMQ.
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
and late lifecycle events do not alter current status. Strictly older lifecycle
events are classified before checking the current-state transition; equal
timestamps follow normal processing. This retains history without replay or
validation against reconstructed historical state. The HTTP API and RabbitMQ
worker reuse this policy. `updated_at` reflects the last applied event's
occurrence time and is not a global monotonic watermark.

## Tests and quality

The default pytest configuration excludes tests marked `integration`, so the
fast local checks do not require Docker services:

```powershell
task test-fast       # concise unit-test output
task test             # default suite; integration tests are excluded
task test-api         # API-layer tests
task lint             # Ruff lint
task format           # format with Ruff
task format-check     # check formatting without changing files
task compile          # compile app and tests
```

For the normal pre-commit check, run:

```powershell
task check
```

`task check` runs `format-check`, `lint`, and the fast test suite. If Ruff
reports fixable lint errors, use `task lint-fix`; use `task format` to rewrite
formatting, then run `task check` again. `task ci` runs `task check` followed by
`task compile`.

### Integration tests

Database integration tests exclusively use `freight_events_test` in the
`postgres-test` service on port `5433`; fixtures apply migrations and clean
tables. The integration marker also includes RabbitMQ tests. Start the isolated
test database and broker first, then configure URLs before pytest imports its
fixtures:

```powershell
docker compose up -d postgres-test rabbitmq
task test-integration
```

`task test-integration` reads `TEST_DATABASE_URL` and `TEST_RABBITMQ_URL` from
the process environment. If you use the Compose defaults, the fixture defaults
already target `postgres-test` and local RabbitMQ. For values stored in `.env`,
load them explicitly before running the task:

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); import pytest; raise SystemExit(pytest.main(['-m', 'integration']))"
```

Alternatively set `TEST_DATABASE_URL` and `TEST_RABBITMQ_URL` in the process
environment before running `task test-integration`. The database must be named
exactly `freight_events_test`. Tests otherwise default to a local PostgreSQL
URL with password `postgres`, which differs from `.env.example`, and a local
RabbitMQ URL. Stop the test services when finished with `docker compose stop
postgres-test rabbitmq`.

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
task outbox-worker   # publish pending recorded-event notifications
```

Always review autogenerated migrations before applying them.

## RabbitMQ worker

RabbitMQ uses the `freight.shipment-events` topic exchange and the versioned
`shipment.event.received.v1` routing key. The worker validates the message and
calls `ReceiveShipmentEvent`; it contains no shipment business rules. The API
remains synchronous. HTTP and worker processing record outbound publication
intent atomically with state/history; a separate outbox worker publishes it.

Retryable processing failures are sent to a retry queue and return to the main
queue after `RABBITMQ_RETRY_DELAY_MS`. After `RABBITMQ_MAX_ATTEMPTS`, or for
invalid messages and business-rule failures, the original message is stored in
the dead-letter queue with attempt and failure metadata. The original delivery
is ACKed after the republish call returns. Publisher confirms and mandatory
routing are not enabled, so return from that call is not proof of broker
acceptance or routing. Start the worker to declare its queues before publishing.
The Compose RabbitMQ service uses a named volume and stable node identity.
Introducing this volume does not migrate data from an older container layer.

Start the broker and worker with:

```powershell
task broker-up
task worker
```

## Transactional Outbox

Apply migrations before starting the updated API and workers (`task db-migrate`
uses `DATABASE_URL`; choose the intended environment explicitly). The current
head adds nullable correlation metadata to existing outbox rows. It preserves
pending messages and their v1 bodies. Start `task outbox-worker` in another terminal.

Creation, applied events and stored late events enqueue one notification per
event/type. Duplicates do not enqueue another; existing history is not backfilled.
The relay locks one due row, publishes `shipment.event.recorded.v1` to
`freight.shipment-notifications`, then records confirmation in PostgreSQL.
The durable destination is `freight.shipment-event-notifications`; it is separate
from ingestion. Downstream subscribers needing independent copies need their
own bound queues. No downstream consumer is included.

The relay uses persistent messages, confirms, mandatory routing and a publication
deadline. Failed attempts remain pending with a fixed retry delay. A confirmation
followed by a commit failure can produce duplicate deliveries with identical
message IDs/bodies. Consumers must deduplicate; ordering is not guaranteed.
Attempts count durably recorded attempts, not every interrupted operation.

Inspect pending work using a database client:

```sql
SELECT id, event_id, correlation_id, created_at, attempts,
       next_attempt_at, last_error
FROM outbox_events
WHERE published_at IS NULL
ORDER BY created_at;
```

For broker outages, restore connectivity/routing and let the relay retry. For
database outages it discards the failed session and reconnects. Persistent
failures are retained indefinitely; retention and operator alert delivery are
not implemented. Stop updated processes before downgrading. Downgrading only
the correlation migration loses correlation metadata; downgrading the outbox
migration destroys publication intent and requires addressing pending work first.

## Observability

API and worker startup configure JSON logs on stdout. `LOG_LEVEL` defaults to
INFO. Logs include fixed operation names, outcomes, timings, correlation and
available event/shipment/message IDs. Raw messages from dependencies, exception
strings, request bodies, SQL and URLs are intentionally excluded; library logs
retain logger, level and exception type when supplied. This reduces secret
exposure at the cost of less detailed third-party diagnostics.

Send `X-Correlation-ID` with 1–64 ASCII letters, digits, `.`, `_` or `-`, or let
the API generate one. Invalid IDs are replaced, not rejected. The response
returns the ID, including error responses. Correlation persists in outbox
metadata and AMQP `correlation_id` across retries and restarts. It never replaces
business `event_id` or transport `message_id`. Old outbox rows fall back to their
message ID; inbound messages without correlation use a valid AMQP message ID or
a new UUID. The v1 JSON envelopes stay unchanged.

| Process | Default metrics URL |
| --- | --- |
| API | `http://127.0.0.1:8000/metrics` |
| Ingestion worker | `http://127.0.0.1:9101/metrics` |
| Outbox worker | `http://127.0.0.1:9102/metrics` |

### View metrics directly

The API exposes Prometheus text from `/metrics`. Start the process you want to
inspect, then query its endpoint from PowerShell:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/metrics | Select-Object -Expand Content
Invoke-WebRequest http://127.0.0.1:9101/metrics | Select-Object -Expand Content
Invoke-WebRequest http://127.0.0.1:9102/metrics | Select-Object -Expand Content
```

The worker endpoints are available only while the corresponding worker is
running. Worker metrics bind to `127.0.0.1` by default; for the Dockerized
Prometheus container to scrape them, set the host to `0.0.0.0` in that worker's
terminal before starting it:

```powershell
$env:METRICS_HOST = "0.0.0.0"
task worker
```

Repeat with `task outbox-worker` in its own terminal. To inspect a particular
Prometheus time series, open `http://127.0.0.1:9090/graph` after monitoring is
started and run a PromQL query such as:

```text
up
freight_http_requests_total
freight_outbox_pending_events
```

The `up` series must be `1` for each process you expect Prometheus to scrape.
For a ready-made view, start the optional monitoring profile and open the
provisioned dashboard:

```powershell
task monitoring-up
```

Then visit `http://127.0.0.1:3000/d/freight-operations` for Grafana or
`http://127.0.0.1:9090` for Prometheus. Allow two scrape intervals for rates to
appear. Stop the monitoring containers with `task monitoring-down`; their named
volumes preserve local history.

Run one process per scrape target/port. Multiple Uvicorn workers sharing a port
are not supported for aggregation. Counters reset on restart and represent
observed attempts, not unique events. IDs are excluded from metric labels.
HTTP uses route templates and an `unmatched` bucket; metrics scrapes are excluded.
Worker `committed` includes successful duplicate handling. Retry/DLQ
`publish_returned` is not a broker confirmation. Outbox `broker_confirmed` and
`published_committed` are separate counters because a commit can fail after
publication. These process observations are not a durable audit trail.

Outbox backlog metrics query PostgreSQL independently of relay transactions.
Pending count includes delayed retries. Oldest age grows during an outage.
If collection fails, `freight_outbox_collection_success` becomes zero and backlog
values are omitted. Check both this metric and Prometheus `up`; an absent series
does not mean an empty backlog. With several relays, use `max` for backlog gauges,
not `sum`, because each reads the same database.

### Optional local dashboard

In terminals running each worker, set `$env:METRICS_HOST = "0.0.0.0"` before
`task worker` / `task outbox-worker`. Run the API with:

```powershell
python -m uvicorn app.api.application:app --host 0.0.0.0 --port 8000
```

The dashboard covers scrape health, HTTP errors/latency, ingestion outcomes,
publication failures and backlog.

The profile scrapes host processes through `host.docker.internal` at ports
8000/9101/9102. If ports change, update `monitoring/prometheus.yml` too. A down
target usually means its process is stopped, bound only to loopback, or blocked
by the host firewall. Prometheus/Grafana UI ports bind to loopback; application
metrics are unauthenticated, so use a trusted development network when opting
into `0.0.0.0`. This is a local monitoring setup, not a production deployment.
Distributed tracing, log aggregation and production alert delivery are deferred.

## Decisions and documentation

Architecture decisions are recorded in [app/docs/adr](app/docs/adr):

- [ADR-001 — Shipment Core Domain and State Machine](app/docs/adr/001-Shipment-Core-Domain-and-State-Machine.md)
- [ADR-002 — Phase 2 API and Persistence Evolution](app/docs/adr/002-Phase-2-API-and-Persistence-Evolution.md)
- [ADR-003 — Atomic Shipment and SHIPMENT_CREATED Persistence](app/docs/adr/003-Atomic-Shipment-and-SHIPMENT_CREATED-Persistence.md)
- [ADR-004 — Concurrent Idempotency Strategy](app/docs/adr/004-Concurrent-Idempotency-Strategy.md)
- [ADR-005 — Out-of-Order Event Treatment](app/docs/adr/005-Out-of-Order-Event-Treatment.md)
- [ADR-006 — RabbitMQ Asynchronous Ingestion](app/docs/adr/006-RabbitMQ-Asynchronous-Ingestion.md)
- [ADR-007 — RabbitMQ Failure Recovery](app/docs/adr/007-RabbitMQ-Failure-Recovery.md)
- [ADR-008 — Transactional Outbox](app/docs/adr/008-Transactional-Outbox.md)
- [ADR-009 — Observability](app/docs/adr/009-Observability.md)

## Next steps

1. Consider confirmed routing for the existing ingestion retry/DLQ publisher;
   outbound outbox publication already uses confirms and mandatory routing.
2. Define retention and production alerting requirements for persistent failures.
3. Add centralized log storage or distributed tracing when operation requires it.

Concurrent HTTP duplicates already recover by rolling back a
`shipment_events_pkey` collision and reloading the persisted shipment. The
worker relies on retries and sequential deduplication instead of that HTTP
recovery path. Neither mechanism serializes distinct events for a shipment.
