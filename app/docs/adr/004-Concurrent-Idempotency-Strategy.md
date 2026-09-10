# ADR-004 — Concurrent Idempotency Strategy

- Status: Accepted
- Date: 2026-09-07
- Reviewed: 2026-09-10
- Related: ADR-003 — Atomic Shipment and SHIPMENT_CREATED Persistence

## Context

`ReceiveShipmentEvent` has sequential duplicate protection:

```text
exists(event_id)
      ↓
process domain
      ↓
save(event)
```

This check is not atomic across independent transactions. Phase 2.6 reproduced
concurrent processing of the same `event_id` using two SQLAlchemy sessions and
real PostgreSQL, synchronizing both executions after the existence check.

The observed result was:

1. both transactions received `exists(event_id) = false`;
2. both ran the handler against their local shipment copies;
3. one transaction committed normally;
4. the other failed on the `shipment_events.event_id` primary-key constraint;
5. after the transactions finished, the database contained one event and one persisted
   shipment transition.

The database constraint protected uniqueness, but the original flow surfaced
an `IntegrityError`. The HTTP route now handles the specific event identity
collision as described below.

## Decision

The platform retains `shipment_events.event_id` as the unique identity and uses
a **database constraint plus explicit conflict handling** as its
concurrent-idempotency strategy.

The implemented flow is:

```text
Receive event
      ↓
Fast sequential duplicate check
      ↓
Process and flush pending writes
      ↓
Unique-constraint conflict?
      ├── no  → processed
      └── yes → rollback, reload shipment, return duplicate outcome
```

The API transaction boundary flushes the pending work so a concurrent
unique-constraint collision can be caught before the response is emitted. It
rolls back, reloads the persisted shipment, and returns that canonical
projection. The domain remains responsible only for validating and applying
transitions to the supplied entity.

No `processed_events` table will be created at this stage. The decision will be
revisited if the system needs intermediate processing states, recoverable
failures, or deduplication before event persistence.

## Alternatives Considered

### `processed_events` table / Inbox Pattern

This provides states such as `RECEIVED`, `PROCESSING`, `PROCESSED`, and
`FAILED`, but adds a model, migration, and abandoned-state recovery. There is
no demonstrated need while the historical event already has a unique identity
and event/projection writes share one database transaction.

### Pessimistic lock per shipment

This serializes events for a shipment, but reduces concurrency and does not by
itself solve a duplicate event identity across shipments or sources.

### Optimistic lock on shipment

This can detect concurrent aggregate updates, but requires versioning and does
not replace the unique `event_id` constraint.

### Serialization per shipment

This was deferred when the decision was made. RabbitMQ ingestion now exists,
but does not implement per-shipment partitioning or serialization across HTTP
requests and workers. Such coordination requires a separate demonstrated need.

## Trade-offs

- A duplicate execution can still reach the handler before failing at commit;
  handlers must therefore remain free of external side effects.
- The duplicate response can only be defined after handling the conflict and
  reloading confirmed state.
- The solution assumes relevant domain effects are persisted in the same
  transaction. Future external effects require an Outbox and idempotent
  consumers.

## Consequences

- PostgreSQL remains the final guarantee of event uniqueness.
- The API test suite validates the defined concurrent-conflict response in
  addition to the PostgreSQL race reproduction test.
- HTTP conflict recovery is implemented. The route recognizes exactly
  `shipment_events_pkey`, rolls back, reloads the shipment, and returns 200.
  Other integrity errors propagate.
- The API test injects a conflict; the PostgreSQL test reproduces the raw
  two-session race. There is no real concurrent HTTP test combining both.
- The worker has no equivalent route-level recovery: commit conflicts enter
  retry classification and a later delivery can find the persisted event.
- This does not serialize different event IDs for one shipment, compare
  conflicting payloads for a reused ID, or guarantee exactly-once execution.
  Handlers must remain free of external effects.
