# ADR-009 — Observability

- Status: Accepted
- Date: 2026-09-10
- Related: ADR-006, ADR-007, ADR-008

## Context

The API, ingestion worker and outbox relay run in separate processes. Durable
publication alone cannot explain which operation failed or how long intents
have waited. Phase 6 baseline validation passed 65 default and 29 integration
tests on 2026-09-10; one formatting issue remains to be normalized.

## Decision

Use standard-library logging with a shared JSON formatter and ContextVar scopes.
Emit only allowlisted fields, never request bodies, URLs, SQL parameters or raw
exception messages. Application operations use fixed names; library records are
reduced to logger/level/error type. Initialize logging at process startup.

Accept X-Correlation-ID containing 1–64 ASCII letters, digits, dots, underscores
or hyphens; otherwise generate a UUID. Return it on HTTP responses. Explicitly
pass it into use cases as optional transport metadata. Persist it in a nullable
outbox column and propagate via AMQP correlation_id, including retries and DLQ.
Old outbox rows use their stable message ID as fallback; old inbound messages
use a valid message ID or a generated UUID. Event identity and v1 bodies do not
change. Domain objects remain independent of observability.

Use prometheus-client counters and histograms with bounded labels. HTTP labels
use route templates, normalized methods and status codes. Worker outcomes
distinguish commit, processing failure, retry/DLQ publish return and ACK failure.
Outbox counters distinguish broker confirmation from committed publication
metadata. Record committed outcomes only after the transaction exits successfully.
Metrics count process observations, not exactly-once business facts.

Expose API /metrics and independent worker HTTP endpoints (9101 ingestion,
9102 outbox). Each process owns a registry; run one process per scrape target.
An outbox-only collector queries pending count and oldest age in an independent
read transaction with a statement timeout. On failure expose collection_success=0
and omit backlog values rather than report zero or stale health.

Provide optional Prometheus/Grafana Compose services and a provisioned dashboard.
Local services scrape host processes through host.docker.internal. Endpoint binds
default to loopback; the monitoring workflow explicitly opts into host access.

## Alternatives and trade-offs

Standard logging avoids another logging dependency but requires formatter and
context tests. Explicit correlation parameters add wiring but avoid ambient
infrastructure dependencies in application/domain code. A database column costs
a migration but survives restarts without changing persisted message bodies.

Scrape-time backlog queries add database load; statement timeout bounds SQL work,
and connection timeout bounds connection establishment. Revisit cached collection
if scale warrants it. Gauges are global database values, so multiple relay targets
must not sum them. Process counters reset on restart and can miss crash windows.

Full distributed tracing, log aggregation, production alert delivery and automatic
multi-process metric aggregation are deferred. Existing ingestion retry/DLQ
publication still lacks confirms/mandatory routing; observability does not improve
that delivery guarantee. Monitoring failures do not change business decisions.

## References

- [Prometheus Python HTTP export](https://prometheus.github.io/client_python/exporting/http/)
- [Custom collectors](https://prometheus.github.io/client_python/collector/custom/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
