# ADR-007 — RabbitMQ Failure Recovery

- Status: Accepted
- Date: 2026-09-09
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
type and message. The worker ACKs the original delivery only after it has
successfully republished it to retry or DLQ.

## Consequences

Transient failures receive bounded retries rather than being silently lost.
Permanent failures and exhausted retries remain inspectable in the DLQ. This is
not exactly-once delivery: a publish/ACK interruption can still redeliver a
message, so consumers continue relying on `event_id` idempotency.
