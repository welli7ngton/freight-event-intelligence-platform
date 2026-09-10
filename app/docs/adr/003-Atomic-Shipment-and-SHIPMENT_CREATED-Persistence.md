# ADR-003 — Atomic Shipment and SHIPMENT_CREATED Persistence

- Status: Accepted
- Date: 2026-09-06
- Reviewed: 2026-09-10
- Related: ADR-002 — Phase 2: API and Persistence Evolution

## 1. Context

Initially, creating a `Shipment` was a domain and persistence operation separate from recording the `SHIPMENT_CREATED` event. That pattern could leave lifecycle history inconsistent: the shipment could be persisted without its creation event; representing creation could depend on another step or HTTP request; and the entity lifecycle and event history were not necessarily treated as one business transaction.

`POST /shipments` is the clear API contract for shipment creation. Correct domain semantics require creation of the entity and creation of its `SHIPMENT_CREATED` event to be one business occurrence. The current architecture establishes a transaction boundary per request through a single SQLAlchemy `Session` from `get_db()`, allowing `Shipment` and `ShipmentEvent` persistence to share a transaction when the use case keeps them cohesive and repositories do not independently finish it.

## 2. Problem

This ADR determines whether `SHIPMENT_CREATED` must be persisted in the creation flow, whether `POST /events` should provide another creation contract, whether `ShipmentEventHandler` should process it as a state transition, and whether entity and event creation can be atomic. The goal is to prevent inconsistencies between current state and event history without putting business rules in controllers or repositories.

## 3. Decision

`CreateShipment` records shipment creation as one business operation. `POST /shipments` is the sole public creation contract; `POST /events` must not be another way to create a shipment.

```text
CreateShipment
    |
    +-- creates Shipment
    +-- creates ShipmentEvent(SHIPMENT_CREATED)
    +-- persists both in the same transaction
    +-- request commits
```

`Shipment.create()` creates the entity in `CREATED`; `SHIPMENT_CREATED` records that historical fact. It does not enter `ShipmentEventHandler` as an ordinary state transition and does not mean `CREATED -> CREATED`.

The event records `shipment_id`, `event_id`, `event_type = SHIPMENT_CREATED`, `source = platform`, `occurred_at`, `received_at`, and `payload`. `occurred_at` is creation time in the domain; `received_at` is the time the platform received or registered it.

`POST /events` remains reserved for operational/lifecycle events. `ReceiveShipmentEvent` rejects `SHIPMENT_CREATED` before loading or changing a shipment with `InvalidShipmentEvent`; the HTTP route returns 422. `ShipmentEventHandler` also rejects it when called directly.

## 4. Current transaction semantics

`get_db()` creates the SQLAlchemy `Session`, supplies that same session to the request repositories, commits on success, rolls back on exceptions, and closes the session at the end. Repositories do not finish the transaction.

```text
Shipment.save() + ShipmentEvent.save()
             |
       request COMMIT
             |
      both persisted
```

If either write fails, the exception triggers rollback and neither record must remain persisted. This preserves integrity between current state and event history.

## 5. Timestamps

The architecture distinguishes `occurred_at` (when the fact occurred in the domain) from `received_at` (when the system received or recorded it). For `SHIPMENT_CREATED`:

```text
Shipment.created_at == ShipmentEvent(SHIPMENT_CREATED).occurred_at
```

ADR-005 now uses occurrence time for independent lifecycle/location ordering.
Historical replay remains future work.

## 6. Layer responsibilities

The HTTP layer receives requests, validates schemas, converts DTOs to application inputs, invokes use cases, and returns responses. It does not create `SHIPMENT_CREATED` directly.

`CreateShipment` creates the domain entity, creates the historical event, persists both in the same transaction, and returns the entity. The domain owns initial state, state validation and transitions, location updates, and business invariants. Repositories only persist; they neither finalize transactions nor put business logic into controllers or events.

## 7. Consequences

Positive consequences are complete history from shipment creation, no second request to record the creation event, transactional consistency of `Shipment` and `SHIPMENT_CREATED`, rollback of partial persistence, a controller without business rules, and a clearer distinction between creation facts and normal lifecycle transitions.

Trade-offs are that `CreateShipment` depends on `ShipmentEventRepository` in addition to `ShipmentRepository`, creation performs two writes in one transaction, `get_db()` must preserve the transaction boundary, and a future asynchronous-publication mechanism may be necessary.

## 8. Alternatives considered

Requiring `POST /events` for the creation event was rejected because it would make shipment creation historically incomplete. Creating the event in the controller was rejected because it would move domain integrity into HTTP. At the time of this decision, an event bus and Outbox were deferred because
the local transaction was sufficient for creation consistency. RabbitMQ ingestion
has since been added (ADR-006/007). Outbox is still planned for HTTP-originated
publication, a separate guarantee from atomic database persistence.

## 9. Final decision

Creating a `Shipment` and creating its `SHIPMENT_CREATED` event are the same business operation and transaction. `POST /shipments` remains the public creation contract; `POST /events` is for later lifecycle events only.

Tests cover joint creation, event identity association, source and timestamps,
and rejection by the use case/handler. A PostgreSQL integration test now injects
an event-repository failure and checks that rollback leaves no shipment. It
fails before flush, so it does not demonstrate rollback after both writes have
reached the server or a commit failure. A dedicated HTTP 422 test is still
absent. See [technical context](../context.md) for current validation results.
