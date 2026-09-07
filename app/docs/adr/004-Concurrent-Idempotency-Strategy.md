# ADR-004 — Concurrent Idempotency Strategy

- Status: Accepted
- Date: 2026-09-07
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
5. after both commits, the database contained one event and one persisted
   shipment transition.

The database constraint protects persisted consistency, but the conflict reaches
the application as an `IntegrityError`. It currently produces a technical error
for the concurrent request rather than a contract-defined duplicate response.

## Decision

In Phase 3A, the platform will retain `shipment_events.event_id` as the unique
identity and use a **database constraint plus explicit conflict handling** as
its concurrent-idempotency strategy.

The planned flow is:

```text
Receive event
      ↓
Fast sequential duplicate check
      ↓
Process and attempt commit
      ↓
Unique-constraint conflict?
      ├── no  → processed
      └── yes → rollback, reload shipment, return duplicate outcome
```

Conflict handling must occur at the transaction boundary after session rollback,
not in the domain or repositories. The domain remains responsible only for
validating and applying transitions to the supplied entity.

No `processed_events` table will be created at this stage. The decision will be
revisited if the system needs intermediate processing states, recoverable
failures, or deduplication before event persistence.

## Alternatives Considered

### `processed_events` table / Inbox Pattern

This provides states such as `RECEIVED`, `PROCESSING`, `PROCESSED`, and
`FAILED`, but adds a model, migration, and abandoned-state recovery. There is
no demonstrated need while the historical event already has a unique identity
and processing is synchronous.

### Pessimistic lock per shipment

This serializes events for a shipment, but reduces concurrency and does not by
itself solve a duplicate event identity across shipments or sources.

### Optimistic lock on shipment

This can detect concurrent aggregate updates, but requires versioning and does
not replace the unique `event_id` constraint.

### Serialization per shipment

This would require queue or coordination infrastructure that does not yet
exist. It is premature before the planned asynchronous processing is added.

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
- Phase 3A must add a test that validates the defined concurrent-conflict
  response in addition to this reproduction test.
- This ADR makes no functional change; it documents the strategy to be
  implemented in the next phase.
