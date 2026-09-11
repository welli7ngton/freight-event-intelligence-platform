# Current Technical Context: Freight Event Intelligence Platform

> Reviewed on 2026-09-10 against the available code, configuration, and tests.
> This document describes implemented capabilities and known limits.
> The README contains the execution commands; ADRs preserve decisions and evolution.

## 1. Current state

The modular monolith includes domain, application, FastAPI, PostgreSQL persistence,
Alembic migrations, RabbitMQ ingestion, bounded retries, DLQ, Transactional
Outbox, and observability (Phases 6 and 7). This does not imply complete
coverage of all production failures. JSON logs, correlation IDs, and metrics are
present in the processes; Prometheus/Grafana are optional in the local Compose setup.

There are no Inbox/processed_events, Redis, full replay, distributed tracing,
centralized log aggregation, or production alert delivery.

## 2. Structure and dependencies

| Directory | Responsibility |
| --- | --- |
| `app/domain/shipment/` | Entity, events, state machine, handler, and exceptions |
| `app/application/ports/` | Repository and publisher protocols |
| `app/application/use_cases/` | Event creation, queries, and receipt |
| `app/application/messaging/` | Versioned contract and serialization |
| `app/api/` | FastAPI routes, Pydantic schemas, and dependencies |
| `app/infra/database/` | SQLAlchemy models, mappers, repositories, and session |
| `app/infra/messaging/` | RabbitMQ and failure classification |
| `app/infra/observability/` | Context, JSON logs, metrics, and backlog |
| `app/infra/config.py` | Environment configuration and .env loading |
| `app/workers/shipment_event_worker.py` | Consumer assembly and per-event transaction |
| `app/workers/outbox_worker.py` | Confirmed relay and metrics endpoint |
| `monitoring/` | Prometheus and Grafana provisioning |
| `alembic/versions/` | Schema evolution |
| `tests/` | Domain, application, API, infrastructure, and integration tests |

Python 3.12+, FastAPI/Pydantic, SQLAlchemy 2 with psycopg, PostgreSQL 17, and Pika
form the stack. Exact versions and tasks are defined in
[pyproject.toml](../../pyproject.toml). The domain does not depend on frameworks,
database, or brokers. Use cases receive ports via injection; adapters reuse the same
rules. Repositories persist data and mappers convert ORM/domain models.

## 3. Domain and events

`Shipment` is a mutable dataclass. `Shipment.create()` starts in `CREATED`.
`ShipmentEvent` is a `frozen=True, slots=True` dataclass containing
`event_id`, `shipment_id`, `event_type`, `source`, `occurred_at`,
`received_at`, `payload`, and `processing_status`. Freezing prevents field reassignment,
but it does not recursively freeze a dict payload.
`LocationUpdatedPayload` is an immutable dataclass for latitude/longitude.

```text
CREATED --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--> DELIVERED
DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED --DELIVERED--> DELIVERED
```

`ShipmentEventHandler` validates shipment identity, rejects
`SHIPMENT_CREATED`, normalizes location, and applies the temporal policy.
`change_status()` consults the state machine; `update_location()` changes
coordinates without changing status. There is no lifecycle transition leaving
`DELIVERED`; location is handled separately by the handler.

`occurred_at` represents the moment the fact occurred; `received_at` represents
registration in the platform. The application generates UTC timestamps. Send
timestamps with timezones: current contracts do not enforce timezone on all input paths.

## 4. Temporal policy

- Location uses `last_location_at`; lifecycle uses `last_lifecycle_at`.
- Events strictly earlier than the corresponding clock receive
  `STORED_OUT_OF_ORDER` and remain in history without altering the projection.
- Equal timestamps are not considered late.
- Non-late events follow the normal update path and receive `APPLIED`.
  Unsupported transitions raise `InvalidStateTransition`.
- Late lifecycle events are classified before the state machine. There is no
  reconstruction of historical state to validate a transition in the past.
- `updated_at` receives `occurred_at` from the last applied event. The two
  clocks are independent; therefore `updated_at` is not a globally monotonic watermark.
- There is no replay or reconciliation of later events.

The handler does not persist, deduplicate, manage transactions, or publish.

## 5. Application and HTTP

Ports: `ShipmentRepository` provides `get/save`;
`ShipmentEventRepository` provides `exists/save/list_by_shipment`;
`ShipmentEventPublisher` provides `publish`; `OutboxRepository` records and selects
intents; `RecordedEventPublisher` publishes notifications for recorded facts.

`CreateShipment` generates a UUID and UTC time, creates the entity and historical
`SHIPMENT_CREATED` event with `source = platform`, and saves both.
`Shipment.created_at == creation_event.occurred_at`.
The event does not represent a `CREATED -> CREATED` transition. Creation and ingestion
also record a publication intent in the same transaction, with an optional correlation ID
passed explicitly by adapters. The domain does not receive observability metadata.

`ReceiveShipmentEvent` rejects external creation, loads the shipment, verifies
`event_id`, calls the handler, registers the result via `dataclasses.replace`,
and saves the history/projection. A sequential duplicate returns the shipment without
reapplying the event. There is no payload comparison for repeated IDs.

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | 200 with `{"status": "ok"}`; does not check the database or broker |
| `GET /metrics` | Prometheus metrics for the API process |
| `POST /shipments` | 201 with ShipmentResponse; the only public creation endpoint |
| `GET /shipments/{shipment_id}` | 200 or 404 |
| `GET /shipments/{shipment_id}/events` | 200, ordered by occurred_at; missing IDs return [] |
| `POST /events` | Synchronous, 200 with ShipmentResponse; does not publish to the broker |

On HTTP ingest, a missing shipment returns 404, an invalid transition returns 409,
and `SHIPMENT_CREATED` returns 422. Schemas validate UUIDs, types, and required fields;
location requires numeric values and excludes booleans. There is no geographic validation
of latitude/longitude limits. HTTP DTOs are converted to application inputs. History exposes
`processing_status`.

## 6. Persistence and atomicity

`DATABASE_URL` is required; there is no URL fallback in the application.
`SessionLocal` uses `autoflush=False` and `expire_on_commit=False`.
`get_db()` provides the same session to request repositories, commits on success,
rolls back on exceptions, and closes the session. Repositories do not commit.
There is no dedicated Unit of Work abstraction.

`shipments` stores the projection, unique reference, status, timestamps,
coordinates, `last_location_at`, and `last_lifecycle_at`.
`shipment_events` has a PK `event_id`, FK to shipment, JSONB payload,
timestamps, and `processing_status`. Mappers preserve enums and payloads.

Existing migrations, in order:

1. `34fe2111c108`: creates shipments and shipment_events, constraints, and indexes.
2. `6f8e4c7a1b2d`: adds location.
3. `8b7c3d2e1f0a`: adds `last_lifecycle_at` and `processing_status`.
4. `9c8d7e6f5a4b`: adds `outbox_events` and a partial pending index.
5. `a1b2c3d4e5f6`: adds nullable `correlation_id` to the outbox without altering bodies.

Alembic uses the environment configuration. Review autogenerated migrations.
The creation flow keeps the entity and history in the same transaction.

## 7. Idempotency and concurrency

The `exists(event_id)` check is not atomic. The PostgreSQL PK prevents two rows
with the same identity. The HTTP route performs a flush and, specifically for
`shipment_events_pkey`, rolls back and returns the reloaded projection.
Other `IntegrityError` exceptions are propagated.

The worker does not implement this HTTP recovery path: a persistence collision is
classified as a failure and retried; a redelivery may find the event already persisted.
Deduplication does not serialize distinct events for a shipment, does not prevent
general lost updates, and does not guarantee single execution of the handler.
For that reason, the handler must remain free of side effects.

## 8. RabbitMQ and recovery

`ShipmentEventMessage` serializes deterministic JSON with
`contract_version = v1`, `message_id`, `event_id`, `shipment_id`, `event_type`,
`source`, `occurred_at`, `received_at`, and a payload dict. The routing key is
`shipment.event.received.v1`, and the default primary exchange is
`freight.shipment-events`. `event_id` remains the business identity.

The worker declares the topology, uses prefetch 1, deserializes the message, and calls
`ReceiveShipmentEvent` in a session. The callback returns after commit; then the consumer
sends ACK. The publisher declares the exchange but not the main queue: the topology must
exist before publishing.

`ShipmentEventFailureClassifier` sends `ValueError` and business exceptions to the DLQ.
`OperationalError`, `OSError`, `TimeoutError`, and unknown exceptions receive bounded retry.
The retry queue TTL returns messages to the main exchange.
Defaults: 5000 ms wait and three total attempts.

The original body is preserved. Headers include `x-attempt-count`,
`x-first-failed-at`, `x-last-error-type`, and `x-last-error-message` (up to 500
characters). The consumer sends ACK after `basic_publish` returns. There are no
publisher confirms or mandatory routing; this return does not prove durable acceptance
or routing. Failures between publish and ACK also allow duplicates.
One should not claim exactly-once delivery or losslessness.

Compose configures a persistent RabbitMQ volume and stable identity. This does not migrate
data from old containers. The confirms limitation above applies to the inbound flow;
the outbound relay uses confirmations and mandatory routing.

### Transactional Outbox (ADR-008)

Creation, applied events, and late events each produce a publication intent per event/type,
regardless of HTTP or RabbitMQ. Duplicates do not create another record; earlier history is
not backfilled. The repository performs ordered flushing of parents so that `event_id`
conflicts continue surfacing before the outbox constraint.

The relay selects an eligible row with `FOR UPDATE SKIP LOCKED` and keeps the transaction
open during limited broker I/O. It publishes the stored envelope
`shipment.event.recorded.v1` with a stable ID, confirmations, and mandatory routing;
then it writes `published_at` and commits. Failures remain pending with a fixed delay.
A failure after confirmation and before commit allows identical republication. There is no
exactly-once guarantee or per-shipment ordering. `Attempts` counts durably recorded operations,
not every interrupted retry attempt.

The `freight.shipment-notifications` exchange and
`freight.shipment-event-notifications` queue are separate from ingestion. No downstream
consumer is included. Repositories do not commit; existing transactional boundaries remain
responsible for commit/rollback.

### Observability (ADR-009)

The ASGI middleware keeps the correlation ID isolated per request, including for synchronous
handlers. `X-Correlation-ID` accepts 1–64 ASCII alphanumeric characters, dots, hyphens,
and underscores; other values generate a UUID. The response returns the ID. The outbox persists
the metadata in a nullable column, sent as the AMQP `correlation_id`.
Retries/DLQ preserve the ID. Old outbox rows use `message_id` as a fallback; inbound messages
without correlation use a valid `message_id` or a UUID. v1 bodies remain unchanged.

JSON logs use an allowlist: UTC timestamp, component, operation, outcome, duration,
available IDs, and error class. They do not render free-form messages, SQL, URLs,
payloads, or exception strings. Libraries may lose message details; logger,
level, and error class remain available.

The API `/metrics` endpoint and workers on 9101/9102 each have their own process registries.
Limited labels use route templates, normalized methods, status, and outcomes; never IDs.
Counters reset on restart and count observations, not unique events.
`broker_confirmed` does not mean `published_committed`. Ingestion `committed`
includes successful duplicates; `publish_returned` from retry/DLQ is not confirmation.

Backlog is queried in an independent session with a small pool, connect timeout, and statement
timeout; it also counts future retries. Failure emits `collection_success=0` and omits gauges
without inventing an empty queue. Use `max`, not `sum`, when aggregating backlog across multiple
relays. One process per target/port; multiprocess Uvicorn is not aggregated.
The optional monitoring profile provides local Prometheus and Grafana dashboards.

## 9. Tests and validation

Validation executed on 2026-09-10:

- Phase 6 baseline: 65 default tests and 29 integration tests passed. The initial gate found
  formatting issues in `recorded_event_message.py`, which were fixed in this phase.
- `task check`: formatting, linting, and **79 default tests passed**; 32 integration tests were
  excluded by configuration. `task compile` passed.
- PostgreSQL/RabbitMQ integration: **32 passed**, loading `.env` before collection and using
  exclusively `freight_events_test` and isolated resources.
- Migration revalidated after expanding coverage: upgrade/downgrade of the correlation column
  preserves a populated outbox; downgrading the outbox preserves history.
- `docker compose --profile monitoring config --quiet` and `promtool check config` passed.
  Grafana loaded the provisioned dashboard with 10 panels.
- Smoke tests with real entry points, test database, and isolated queues: three Prometheus targets
  were UP, the correlation header was present in the API, and backlog collection was healthy.
  Temporary processes were terminated and broker resources from the smoke test were cleaned up.

Coverage includes rollback after flush, real concurrent HTTP races, relay locks,
confirmation followed by commit failure, republication with stable identity/body and correlation ID,
422 for external creation, commit before ACK in the producer callback, broker deadlines,
context isolation, logs without sensitive strings, failure metrics, and HTTP → database → broker
propagation.

Non-blocking warnings: Starlette/AnyIO deprecations and a constant HTTP 422; the sandbox also
prevented writing the optional pytest cache during `task check`.
Integration was executed with `-p no:cacheprovider`. An initial naming conflict between test
modules was resolved before the full run completed.

See [README](../../README.md#integration-tests) to load URLs before collection. The database must
be named exactly `freight_events_test`; fixtures apply migrations and clean tables. RabbitMQ uses
`TEST_RABBITMQ_URL`.
Do not run these fixtures against the development database.

## 10. Next decisions

ADR-008 and ADR-009 record Phases 6 and 7. Future decisions depend on requirements: confirms/
routing for inbound retry/DLQ, outbox retention, alerts, log aggregation, or tracing. Monitoring
does not change delivery guarantees.
No migrations are applied to the development database in this implementation.
