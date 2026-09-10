# ADR-007 — RabbitMQ Failure Recovery

- Status: Accepted
- Date: 2026-09-09
- Reviewed: 2026-09-10
- Related: ADR-006

## Context

The Phase 4 worker ACKed successful messages and rejected every failure. That
made processing failures terminal without enough operational context and could
not distinguish temporary infrastructure failures from invalid business input.

## Decision

The worker uses a centralized `ShipmentEventFailureClassifier`.

- Invalid messages, unknown shipments, invalid state transitions, and invalid
  shipment event types are non-retryable and go directly to the DLQ.
- Database operational failures, timeouts, OS errors, and unknown exceptions
  are retryable.

The topology contains a durable main queue, retry exchange/queue, and DLQ
exchange/queue. A retry queue TTL returns messages to the main exchange after
the configured delay. `RABBITMQ_MAX_ATTEMPTS` counts total delivery attempts;
the default is three. Exhausted retryable messages go to the DLQ.

The original message body is never changed. Retry/DLQ publications retain and
extend headers with `x-attempt-count`, first-failure time, and the latest error
type and message. The exact headers are `x-attempt-count`,
`x-first-failed-at`, `x-last-error-type`, and `x-last-error-message`; the
error message is truncated to 500 characters. The worker ACKs the original
delivery after the retry/DLQ `basic_publish` call returns. The call does not
use publisher confirms or mandatory routing, so this is not confirmation of
durable broker acceptance or routing.

## Consequences

Transient failures are routed toward bounded retries; permanent and exhausted
failures are routed toward the DLQ for inspection. Without publisher confirms
and routing checks, this implementation does not guarantee loss-free handoff.
A publish/ACK interruption can also cause redelivery, so consumers continue
relying on `event_id` idempotency. The Compose RabbitMQ service has no persistent
volume; durable flags alone do not survive removal of its container.

Unit tests cover retry metadata, exhaustion, invalid-message DLQ routing, and
classification of invalid transitions. A broker integration test checks that
an invalid body is preserved in the DLQ. There is no integrated test for TTL
redelivery followed by success or a broker failure during publish/ACK.
See [technical context](../context.md) for dated validation.
