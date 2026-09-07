# ADR-002 — Phase 2: API and Persistence Evolution

- Status: In progress
- Date: 2026-09-06
- Related: ADR-001 — Shipment Core Domain and State Machine

## 1. Context

Phase 1 established the Freight Event Intelligence Platform domain with the `Shipment` entity, immutable events, a state machine, transition rules, and unit tests.

The next evolution introduced the Phase 2 foundation: an Application Layer, PostgreSQL persistence, and a FastAPI HTTP layer. This ADR records what has actually been implemented, corrections made to contracts between layers, and the outstanding work that prevents Phase 2 from being complete. Repository code is the source of truth; features marked as planned are not yet implemented.

## 2. Decision status

The project remains in **Phase 2 — API/Persistence, in progress**. The domain foundation is implemented, and the Application Layer, persistence infrastructure, and FastAPI assembly have an initial validated integration. HTTP tests in the environment, PostgreSQL integration tests, and broader processing policies are still needed.

## 3. Implemented changes

### 3.1 Domain

The domain includes the `Shipment` entity; immutable `ShipmentEvent` with `event_id`, `shipment_id`, type, source, and timestamps; `ShipmentEventType`; `ShipmentStatus`; `ShipmentStateMachine`; `InvalidStateTransition`; and `ShipmentEventHandler`.

```text
CREATED --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--> DELIVERED
DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED --DELIVERED--> DELIVERED
```

The handler validates that an event belongs to the correct shipment. `LOCATION_UPDATED` updates location; other events go through the state machine.

### 3.2 Timestamps and location

Domain contracts use `event.occurred_at` as the timestamp of an event-caused change. `change_status` and `update_location` update `updated_at`. `Shipment` has `current_latitude`, `current_longitude`, and `last_location_at`. The handler accepts `LocationUpdatedPayload` or a compatible API dictionary, which it converts before calling the entity.

### 3.3 Application Layer

Ports defined with `Protocol` are `ShipmentRepository` (`get`, `save`) and `ShipmentEventRepository` (`save`, `list_by_shipment`). The implemented use cases are `CreateShipment`, `GetShipment`, `GetShipmentEvents`, and `ReceiveShipmentEvent`.

`CreateShipment` generates the shipment UUID and UTC timestamp, creates its associated historical `SHIPMENT_CREATED` event, and sends both to their repositories. `ReceiveShipmentEvent` rejects `SHIPMENT_CREATED`, fetches the shipment, checks `event_id` idempotency, processes the event through the handler, and saves the event and shipment.

### 3.4 Persistence

SQLAlchemy infrastructure with psycopg includes a declarative `Base`, a `DATABASE_URL`-configured engine, `SessionLocal`, `ShipmentModel`, `ShipmentEventModel`, entity/ORM mappers, and SQLAlchemy shipment and event repositories.

`shipments` stores current state. `shipment_events` stores event history with a foreign key to `shipments.id` and JSONB payloads. The mapper converts persisted status strings to `ShipmentStatus` and preserves location. The event repository converts dataclass payloads to dictionaries before JSONB storage.

### 3.5 Migrations

The initial migration creates `shipments`, `shipment_events`, primary keys, the event foreign key, a unique `reference_number` index, and indexes for status, shipment, event type, and `occurred_at`. A second migration adds `current_latitude`, `current_longitude`, and `last_location_at` to `shipments`. The location migration was successfully applied to local PostgreSQL with `alembic upgrade head`.

### 3.6 HTTP API

A FastAPI application in `app/api/application.py` provides shipment and event routers:

- `POST /shipments`
- `GET /shipments/{shipment_id}`
- `GET /shipments/{shipment_id}/events`
- `POST /events`

Implemented Pydantic schemas are `CreateShipmentRequest`, `ShipmentResponse`, `ShipmentEventRequest`, and `ShipmentEventResponse`. They validate required fields, length limits, UUIDs, timestamps, and event types. API dependencies create SQLAlchemy sessions, repositories, and use cases.

## 4. Implemented tests

Coverage includes entity and state-machine tests, immutable `ShipmentEvent`, rejection of events belonging to another shipment, in-memory repository use cases, `CreateShipment` identity and timestamp generation, event receipt and shipment updates, mapper conversion with status and location, shipment and event schema validation, and a FastAPI application test.

The suite includes domain, application, API, schema, and infrastructure tests. When this documentation was validated, 37 tests passed. A Starlette/AnyIO deprecation warning did not cause a test failure.

## 5. Current issues and resolutions

### 5.1 FastAPI dependency injection

Resolved: `get_receive_shipment_event_use_case` now supplies `ShipmentEventHandler` and uses the correct `shipment_event_repository` argument. Factories declare `Depends(get_db)`; the application imports successfully and OpenAPI confirms shipment, event, and health routes.

### 5.2 TestClient dependency

The application test uses `fastapi.testclient.TestClient`. The installed Starlette version requires `httpx2`, declared as a development dependency and available in the validated environment.

### 5.3 Health check

Resolved: `GET /health` returns `{"status": "ok"}` and is part of the API's minimum contract.

### 5.4 API/Application boundary

Resolved: `POST /shipments` explicitly converts `CreateShipmentRequest` to `CreateShipmentInput`. HTTP and application contracts remain separate.

### 5.5 Transaction

`get_db` commits successful requests, rolls back on exceptions, and always closes the session. Repositories do not commit. The same Session is used by a request's repositories, so shipment creation plus `SHIPMENT_CREATED`, and lifecycle event receipt, share the same commit or rollback. There is no dedicated Unit of Work yet.

`SHIPMENT_CREATED` is a historical event, not a `CREATED -> CREATED` transition. `ReceiveShipmentEvent` and `ShipmentEventHandler` reject it with `InvalidShipmentEvent`; `POST /events` maps that to HTTP 422.

### 5.6 Idempotency

The use case has an initial policy: `ShipmentEventRepository` exposes `exists(event_id)`; the SQLAlchemy repository checks the primary key before processing; and a persisted event returns the shipment without reapplying a transition or saving a duplicate. There is no `processed_events` table or complete protection from concurrent consumer races yet.

### 5.7 Out-of-order events

Events are queried by `occurred_at`, but no acceptance, rejection, storage, or reprocessing policy exists for out-of-order arrival.

### 5.8 Payloads by event type

The HTTP schema validates numeric latitude and longitude for `LOCATION_UPDATED`, and the handler normalizes its dictionary to `LocationUpdatedPayload`. `ShipmentEvent.payload` remains `object` in the domain and `dict` in HTTP; there are no type-specific schemas yet.

## 6. Planned work

Not yet implemented: RabbitMQ; producers and consumers; workers; retries; dead-letter queues; Redis; complete concurrent idempotency and a dedicated table; out-of-order-event handling; Transactional Outbox; `processed_events` and `outbox_events`; structured logging; Prometheus metrics; Grafana dashboards; and complete integration tests.

## 7. Consequences

### Positive

- The domain remains independent of FastAPI, SQLAlchemy, and PostgreSQL.
- The Application Layer has explicit repository contracts.
- Current state and event history have separate persistence models.
- API schemas validate input before processing.
- Migrations evolve the schema without recreating tables.
- Core domain and application contracts have unit tests.

### Negative

- Atomicity coverage uses in-memory SQLite; complete PostgreSQL integration tests are missing.
- No dedicated Unit of Work limits more complex atomic operations.
- Current idempotency does not cover concurrent races or use a dedicated table.
- Payload handling remains weakly typed.

## 8. Next steps

1. Add endpoint and repository integration tests with PostgreSQL.
2. Introduce a Unit of Work if atomicity needs a boundary beyond the current session lifecycle.
3. Strengthen idempotency against races and evaluate `processed_events`.
4. Define an out-of-order-event policy.
5. Implement RabbitMQ, retries, DLQ, and Outbox in later phases.

## 9. Decision

Phase 2 must preserve the separation of domain, application, infrastructure, and API. The API may orchestrate HTTP input and output but must not absorb business rules or directly access the ORM outside infrastructure dependencies.

Phase 2 still has PostgreSQL-integration and processing-policy work outstanding, although the 37-test suite passes. `get_db()` defines the request transaction lifecycle.
