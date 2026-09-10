# Phase 6 — Transactional Outbox implementation plan

- Status: Proposed — awaiting user approval; implementation has not started.
- Prepared: 2026-09-10.
- Scope: durable publication intent and recoverable outbound publication.
- Related: [current context](../context.md), ADR-003 through ADR-007.

## 1. Problem and expected outcome

HTTP currently commits shipment state and event history without publishing a
message. Publishing directly before or after commit creates a failure window:
the database can succeed while publication fails, or publication can succeed
while the database rolls back.

Persist an outbound message alongside the business writes, then publish it from
a separate process. A successful business transaction must leave both its
history and publication intent committed. A broker outage must not prevent
acceptance while PostgreSQL remains available. Outbox insertion failure must
roll back the business transaction.

Publication remains at least once: a broker confirmation followed by a database
failure can cause republication. The same message ID and content must be reused.
Broker confirmation does not mean downstream business processing completed.

## 2. Proposed scope and message semantics

Create one outbound notification for every newly recorded event after rollout:

| Input | Outbox behavior |
| --- | --- |
| POST /shipments | Notification for internal SHIPMENT_CREATED |
| POST /events, new applied event | Notification with APPLIED |
| POST /events, accepted late event | Notification with STORED_OUT_OF_ORDER |
| RabbitMQ ingestion, new event | Same notification semantics as HTTP |
| Sequential or concurrent duplicate | No additional notification |
| Invalid input or rolled-back transaction | No committed notification |

Including worker-originated events keeps publication a property of recording a
business fact rather than its transport. Including creation provides complete
notifications from shipment initialization. These are proposed scope choices
for approval. Historical rows are not backfilled automatically.

Keep HTTP response bodies and status codes synchronous and unchanged.

Introduce `shipment.event.recorded.v1`, distinct from the existing inbound
`shipment.event.received.v1`. Its deterministic envelope contains contract
version, message ID, event ID, shipment ID, event type, source, occurrence and
receipt timestamps, payload, and processing status. Use the outbox ID as the
stable message ID. Store the completed envelope; do not rebuild it from a later
shipment projection during retries.

Use a separate durable outbound topic exchange, proposed default
`freight.shipment-notifications`, with routing key `shipment.event.recorded.v1`.
Declare a durable notification queue, proposed default
`freight.shipment-event-notifications`, bound to that key. It provides a real
destination before downstream consumers exist. The ingestion queue is never
bound to this exchange. A future subscriber requiring its own copy needs a
separate queue, rather than sharing a work queue with another subscriber.

The extra contract and topology prevent ingestion feedback and make creation
and late-event notifications explicit. The trade-off is another schema and queue
to maintain. No downstream application or notification consumer is included.

## 3. Application and transaction boundaries

Add a required OutboxRepository Protocol to CreateShipment and
ReceiveShipmentEvent. Enqueue after successful domain handling/history recording;
the existing duplicate return occurs before enqueueing. Share small message
construction logic where useful, without introducing a general event bus.

Wire SQLAlchemy repositories to the same Session in API dependencies and the
ingestion worker. Existing request and worker boundaries own commit/rollback;
repositories and use cases do not commit or connect to RabbitMQ. Keep domain
classes unchanged. Update in-memory factories and all use-case constructors.

Add an infrastructure-neutral outbound message/publisher port. Preserve the
existing inbound publisher's public contract; share small RabbitMQ publication
helpers only where they simplify confirmed publishing without mixing message
semantics. The relay worker assembles the session, repository and publisher.
An application operation coordinates one pending publication through ports;
SQLAlchemy locking remains in infrastructure.

A dedicated general-purpose Unit of Work is deferred: the shared Session already
provides atomicity. The cost is continued explicit transaction wiring in both
entry points, verified with integration tests.

## 4. Storage and migration

Add an additive Alembic migration after `8b7c3d2e1f0a`:

| outbox_events field | Purpose |
| --- | --- |
| id, UUID primary key | Stable message identity across retries |
| event_id, UUID foreign key | Link to the recorded shipment event |
| shipment_id, UUID | Aggregate identity for inspection |
| message_type | Versioned outbound contract/routing identity |
| payload, JSONB | Complete immutable outbound envelope |
| created_at, timezone-aware | Time publication intent was created |
| published_at, nullable | Time confirmed publication was recorded in PostgreSQL |
| attempts, nonnegative integer | Count of publication attempts recorded durably |
| next_attempt_at | Earliest retry time |
| last_error, nullable bounded text | Most recent publication error, excluding secrets |

Add uniqueness on `(event_id, message_type)` and a partial pending-work index
covering next_attempt_at/created_at where published_at is null. Use pending vs.
published derived from published_at; do not add PROCESSING state or leases.

Explicitly test SQLAlchemy write ordering for shipment, event and outbox foreign
keys. Preserve HTTP duplicate recovery: if the additional unique constraint can
surface before the event PK, recover only a verified existing event/notification
identity, never every IntegrityError. Roll back the losing transaction fully.

Migration upgrade/downgrade must be tested with existing shipment/event rows.
Downgrading removes outbox data; document that workers must stop and pending
publication intent must be addressed before rollback. No automatic historical
backfill, data purge, retention job, or deletion of published rows in this phase.

## 5. Relay and recovery algorithm

1. Open a database transaction and select one due pending row ordered by
   next_attempt_at, created_at, and ID, using FOR UPDATE SKIP LOCKED.
2. Publish its stored envelope with persistent delivery mode, publisher confirms
   and mandatory routing. Treat a nack, unroutable return, timeout or disconnect
   as an unsuccessful or uncertain attempt.
3. On confirmation, update published_at and attempts, then commit.
4. On publication failure, retain the row, record attempts/last_error, schedule
   next_attempt_at using a configurable fixed delay, and commit that metadata.
5. On database failure, roll back, discard the session, wait, and reconnect.
   A crash releases row locks; the pending row remains recoverable.
6. Sleep when idle. Bound connection/blocked-publication waits and ensure orderly
   shutdown releases connections and transactions. Validate supported timeout
   behavior against the installed Pika version and test interruption paths.

Use one row per transaction initially so a slow publish holds only one outbox
row lock. Multiple relay processes skip locked rows. This prevents simultaneous
ownership of a row, but cannot eliminate republication after uncertain outcomes.
It also does not provide strict per-shipment ordering or serialize domain writes.

Holding a PostgreSQL transaction during broker I/O is a deliberate small-system
trade-off: fewer recovery states than a claim/lease protocol, at the cost of a
connection and row lock during publication. Revisit leases/batching if measured
throughput or lock duration requires them. Attempts are not an exact audit of
crashed attempts whose metadata never committed.

Outbox retry is separate from inbound consumer retry/DLQ. Keep failed intents
pending with a fixed configurable delay instead of discarding them after three
attempts. Persistent failures remain inspectable and require operator repair;
monitoring, alerting and an admin retry UI are outside this phase.

## 6. Broker and local operation

Add `task outbox-worker`, outbound exchange/queue configuration, poll interval,
retry delay and bounded network-wait settings to configuration and .env.example.
The relay declares outbound topology before publishing. A missing binding must
never lead to a published_at value on an unroutable message.

Add a named RabbitMQ data volume and stable node identity to local Compose so
broker storage persists across container recreation. Document that introducing
the volume does not migrate messages already in the current container layer;
do not recreate the running broker or delete its data as an implicit setup step.
Use isolated broker resources for validation.

Confirms/mandatory routing are required for the new outbound relay path. General
hardening of existing ingestion retry/DLQ publication is deferred and must remain
documented as a separate limitation. Do not claim end-to-end loss-free delivery
for every path after implementing Outbox.

## 7. Implementation sequence and files

1. **Record the design.** Create ADR-008-Transactional-Outbox.md with the approved
   semantics, alternatives, guarantees and limitations before application edits.
2. **Add message and storage contracts.** New files under
   app/application/messaging/, app/application/ports/, and
   app/infra/database/{models,mappers,repositories}/, plus a migration. Register
   the new ORM model in models/__init__.py and Alembic metadata imports.
3. **Make enqueueing atomic.** Update create_shipment.py,
   receive_shipment_events.py, api/dependencies.py, the ingestion worker, test
   factories, API overrides and database cleanup fixtures.
4. **Implement confirmed relay.** Add the application publication operation,
   RabbitMQ outbound adapter/topology and app/workers/outbox_worker.py; add
   configuration, task commands and local broker storage configuration.
5. **Validate failure behavior.** Add domain-independent application tests,
   real PostgreSQL transaction/concurrency tests, and real RabbitMQ publishing
   tests. Run the existing regression suite.
6. **Update operational docs.** README, technical context, AGENTS.md and relevant
   ADR follow-up notes; include migration order, startup, pending-row inspection,
   recovery, duplicate semantics and tested limits.

Existing unrelated work must be preserved. As Alembic metadata registration is
already in scope, resolve its known import-order/formatting issue and verify the
quality gate. Do not expand this into general refactoring.

## 8. Acceptance and verification

- Creation commits one shipment, one historical event and one notification.
- Applied and late events from both adapters commit exactly one intent per
  newly recorded event, with the correct processing status and envelope.
- Force failure after writes are flushed; a new independent database session
  must see neither partial business changes nor outbox intent after rollback.
- Sequential duplicate delivery and a real concurrent HTTP race leave one event
  and one intent, preserving the existing HTTP duplicate outcome.
- The ingestion worker commits event/outbox before ACK; verify the production
  transaction callback, not a use case with commit deferred until after ACK.
- Broker unavailability does not break HTTP acceptance. A later relay run
  publishes pending messages and records confirmation.
- Nack, unroutable delivery and timeout never mark a row published.
- Inject failure after confirmed publish but before database commit; replay uses
  the same message ID/body. Verify duplicates are possible and identifiable.
- Two independent relay sessions cannot claim the same locked row; other due
  rows remain available. Crashes/rollback release ownership without a stuck state.
- Failed retries persist error/schedule metadata when PostgreSQL is available;
  already-published rows are not normally selected again.
- Outbound notifications never enter the ingestion queue. Validate durable
  topology, actual queue delivery and message envelope with RabbitMQ.
- Migration works on populated schemas; integration cleanup includes outbox rows.
- Run task check, task compile and the integration suite with TEST_DATABASE_URL
  targeting exactly freight_events_test and isolated RabbitMQ test resources.
  Record actual outcomes and any unavailable infrastructure separately.

## 9. Approval boundary

Only this plan is being created now. Approval authorizes the implementation
sequence above, including the additive migration, tests, configuration and docs.
It does not imply production deployment, applying migrations to a non-test
database, recreating the current broker, or deleting existing messages.

## 10. Technical references

Publisher confirms establish broker-side confirmation, independently of consumer
processing: [RabbitMQ acknowledgements and confirms](https://www.rabbitmq.com/docs/confirms).
The proposed PostgreSQL queue selection uses row locks and skips rows held by
other workers: [PostgreSQL 17 SELECT locking clauses](https://www.postgresql.org/docs/17/sql-select.html).
Pika documents confirmed publication for BlockingConnection:
[delivery-confirmation example](https://pika.readthedocs.io/en/stable/examples/blocking_delivery_confirmations.html).
Verify the implementation against this repository's pinned Pika 1.3.2 rather
than assuming every feature in the latest documentation is available.
