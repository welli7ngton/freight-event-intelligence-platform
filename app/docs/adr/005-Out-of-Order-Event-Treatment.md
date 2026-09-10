# ADR-005 — Out-of-Order Event Treatment

- Status: Accepted
- Date: 2026-09-09
- Reviewed: 2026-09-10
- Related: ADR-001, ADR-004

## Context

Carrier and operational systems can deliver correct facts late. Broker ordering
cannot prevent this: producers can report older facts after newer ones and
retries can reorder delivery. Rejecting valid late events loses operational
history; applying them blindly can regress the current shipment projection.

## Decision

The platform persists every valid, non-duplicate event. The record stores one
of two processing outcomes: `APPLIED` for an event that updates the current
projection, and `STORED_OUT_OF_ORDER` for a retained historical event that does
not update it.

`LOCATION_UPDATED` is compared with `Shipment.last_location_at`. A late
location remains in history without overwriting the current coordinates.
Lifecycle events use the independent `Shipment.last_lifecycle_at`; a late
lifecycle event remains in history without changing status. Otherwise, a
lifecycle event follows the existing state machine and an undefined transition
is rejected. The comparison is strictly older (`<`); equal timestamps follow
normal processing. Late lifecycle classification occurs before the transition
lookup, so those events are not checked against a reconstructed historical
state. Location payload normalization occurs before its timestamp comparison.

The domain handler owns this policy. The synchronous API and implemented
RabbitMQ worker use the same `ReceiveShipmentEvent` application use case.
The policy does not depend on broker ordering.

## Consequences

The current shipment view cannot move backward in either timeline, while the
complete event history remains auditable and is suitable for future replay or
reconciliation. This version does not replay later events after accepting a
late event; full time-ordered reconciliation remains future work.

The independent clocks do not make `updated_at` globally monotonic: it is set
to the occurrence time of the last applied event, even when the other timeline
has a newer timestamp. These are handler semantics on the supplied projection,
not a guarantee against lost updates from concurrent distinct events.

Domain and application tests cover late-event retention and independent clocks;
a PostgreSQL-backed HTTP test checks persisted history and projection behavior.
Dated execution results are maintained in [technical context](../context.md).
