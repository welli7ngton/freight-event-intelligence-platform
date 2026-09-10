# ADR-002 — Phase 2: API and Persistence Evolution

- Status: Accepted
- Date: 2026-09-06
- Reviewed: 2026-09-10
- Related: ADR-001; refined by ADR-003 through ADR-007

## Context

Phase 1 established the infrastructure-independent Shipment domain. Phase 2
introduced application orchestration, PostgreSQL persistence, and HTTP access.
The original record described an incomplete implementation; the foundation and
subsequent ingestion capabilities are now implemented. This update preserves
the layer decision and records later refinements without treating the Phase 2
snapshot as the current project status.

## Decision

Keep domain, application, API, and infrastructure separate:

- Domain owns Shipment initialization, state transitions, location updates, and
  business exceptions.
- Application use cases orchestrate operations through injected `Protocol`
  ports: `ShipmentRepository`, `ShipmentEventRepository`, and, added later,
  `ShipmentEventPublisher`.
- API schemas validate transport input and routes convert DTOs to application
  inputs, invoke use cases, and translate responses/errors.
- Infrastructure owns SQLAlchemy models, mappers, repositories, sessions, and
  broker adapters. Repositories do not commit.

This separation lets HTTP and RabbitMQ share the same use cases and domain
rules. The trade-off is explicit conversion and dependency assembly.

## Implemented API and application

`CreateShipment`, `GetShipment`, `GetShipmentEvents`, and
`ReceiveShipmentEvent` are implemented. Creation uses `CreateShipmentInput`;
it records the shipment and historical `SHIPMENT_CREATED` event together
(ADR-003). External ingestion rejects that event type with HTTP 422.

The API exposes health, shipment creation/query, event history, and synchronous
event ingestion. Creation returns 201; ingestion returns 200 with the shipment.
Unknown shipment queries/ingestion return 404. History for an unknown ID is an
empty list. Invalid lifecycle transitions return 409.

`LOCATION_UPDATED` updates coordinates independently of status.
`SHIPMENT_DEPARTED` moves PICKED_UP or DELAYED to IN_TRANSIT. Changes use
`occurred_at`; receipt time is recorded separately. Pydantic validates numeric
coordinates on HTTP input; the domain event payload remains broadly typed.

## Persistence and transactions

`shipments` stores current state; `shipment_events` stores event history,
with a foreign key, globally unique event identity, JSONB payload, and processing
status. Three migrations create the base schema, add location fields, and add
the lifecycle clock/event classification.

`get_db()` supplies the same SQLAlchemy Session to a request's repositories,
commits successful work, rolls back errors, and closes the session. This makes
shipment and event writes atomic without a dedicated Unit of Work abstraction.
Introduce another transaction abstraction only when a concrete use case needs it.

## Later decisions

- ADR-003 formalizes atomic creation and creation-event semantics.
- ADR-004 retains the event primary key and adds HTTP flush/conflict recovery.
  Sequential deduplication alone is not concurrency protection.
- ADR-005 adds durable late-event classification using independent clocks.
- ADR-006 introduces RabbitMQ while retaining synchronous HTTP.
- ADR-007 adds bounded retries and DLQ.

Outbox, Inbox/processed_events, replay, Redis, structured logging, and metrics
remain unimplemented. General concurrent aggregate update protection is also
not provided by event identity deduplication.

## Alternatives and trade-offs

Keeping rules in controllers or ORM models would couple domain behavior to
transport or storage. Ports and mappers avoid this at the cost of more explicit
types and wiring. A separate Unit of Work is deferred because the current
session lifecycle already supplies the transaction boundary; duplicate HTTP
conflict handling currently remains in the route.

FastAPI TestClient uses the declared `httpx2` development dependency.
Default tests use in-memory adapters. PostgreSQL integration tests cover
repositories, constraints, rollback, HTTP flow, and duplicate races; messaging
integration was added in later phases. These tests exist, but their presence
alone does not establish a passing integration environment or complete failure
coverage. See [technical context](../context.md#9-testes-e-validação) for dated
validation and known test limitations.

## Consequences

The API and persistence foundation is implemented. Business rules remain
reusable from multiple adapters, state/history share a transaction, and schema
changes use migrations. The next planned architecture decision is Transactional
Outbox for reliable publication intent, followed by observability.
