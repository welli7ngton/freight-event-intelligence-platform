# ADR-008 — Transactional Outbox

- Status: Accepted
- Date: 2026-09-10
- Related: ADR-003, ADR-004, ADR-006, ADR-007
- Approved implementation: [Phase 6 plan](../plans/phase-6-transactional-outbox.md)

## Context

Shipment state and history commit together, but publishing separately cannot
atomically coordinate PostgreSQL and RabbitMQ. A broker outage must not discard
the intention to notify other systems of a recorded event.

## Decision

Create one outbox row per newly recorded event and notification type in the same
Session and transaction as state/history. Both creation and operational ingestion
use a required application OutboxRepository port. Applied and stored-out-of-order
events from HTTP and RabbitMQ produce notifications; duplicates do not. Existing
history is not backfilled. The domain and synchronous HTTP contract stay intact.

Publish the stored `shipment.event.recorded.v1` envelope to a separate outbound
exchange and durable queue. It includes processing_status and uses the outbox ID
as a stable message ID. It is not an instruction to the ingestion consumer.

A relay locks one due pending row with FOR UPDATE SKIP LOCKED, publishes with
confirms, persistent delivery and mandatory routing, then records published_at
and commits. Publication failures remain pending with a fixed retry delay and
safe error classification. Database failures roll back and retry with a new
session. Counts include durably recorded attempts, not all interrupted attempts.

## Alternatives and trade-offs

Direct publication before/after commit can produce phantom or missing messages.
A distributed transaction is not assumed. A general Unit of Work adds little
while the existing session boundaries provide atomicity.

Holding one row lock during bounded broker I/O is simpler than leases and
PROCESSING recovery states, at the cost of a database connection and transaction
per active publish. Revisit claims/batching when throughput justifies it.

An uncertain confirmation or failure after publication but before database commit
can cause a duplicate with the same identity/body. Consumers must deduplicate;
neither exactly-once processing nor strict per-shipment ordering is promised.
Failed intents are retained indefinitely; retention and operational alerting are
future work. Confirmations establish broker acceptance, not consumer completion.

## Consequences

New business writes and publication intent are atomic. The relay can recover from
broker outages independently of HTTP availability. New storage, a worker and
outbound topology require operation and inspection. Local Compose uses persistent
broker storage with stable identity; enabling it does not migrate data from an
existing container. The existing inbound retry/DLQ publisher's weaker guarantees
are a separate limitation and are not changed by this decision.

Validation covers independent-session rollback, duplicate HTTP races, relay locks,
retry scheduling, stable republication, actual broker delivery and unroutability.
See [technical context](../context.md) for execution results and operational limits.
