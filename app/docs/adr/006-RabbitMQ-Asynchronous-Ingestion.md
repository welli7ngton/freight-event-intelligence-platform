# ADR-006 — RabbitMQ Asynchronous Ingestion

- Status: Accepted
- Date: 2026-09-09
- Reviewed: 2026-09-10; failure handling refined by ADR-007
- Related: ADR-004, ADR-005

## Context

The platform needs an asynchronous adapter without moving shipment rules into
a worker or changing the synchronous HTTP contract prematurely. A broker can
redeliver messages, so consumers must remain idempotent.

## Decision

RabbitMQ is added as a Phase 4 infrastructure adapter. The broker contract is
the deterministic, versioned `shipment.event.received.v1` message, containing a
message ID, event identity, shipment identity, event type, source, occurrence
and receipt timestamps, and payload. It is routed through the durable
`freight.shipment-events` topic exchange to the ingestion queue.

The worker deserializes and validates the contract, invokes
`ReceiveShipmentEvent`, and ACKs only after the use case's database transaction
commits. The initial Phase 4 implementation rejected failed deliveries without
requeue; ADR-007 supersedes that failure policy with implemented bounded retries
and DLQ routing.

`POST /events` remains synchronous and authoritative. It does not publish to
RabbitMQ yet. Publishing after the API transaction commits is intentionally
deferred to Phase 6 Transactional Outbox, which will make the intention to
publish durable alongside the shipment update.

## Consequences

External adapters can now send operational shipment-event messages through
RabbitMQ and obtain the same domain behavior as the HTTP API. Event identity
and the existing idempotency policy protect repeated deliveries. There is no
automatic notification for API-accepted events until Outbox is implemented.

## Implementation limits

The worker owns commit; the generic consumer ACKs when its callback returns.
Callbacks must therefore complete their transaction before returning. The
current broker ingestion integration test passes the use case directly and
commits afterward, so it does not verify production worker commit/ACK ordering.

The publisher declares the exchange but does not declare/bind the ingestion
queue. Start the worker to establish topology before sending messages. Messages
use persistent delivery mode, but publisher confirms and mandatory routing are
not enabled. A publish call returning does not prove durable acceptance or
routing, and the local Compose broker has no persistent data volume.
