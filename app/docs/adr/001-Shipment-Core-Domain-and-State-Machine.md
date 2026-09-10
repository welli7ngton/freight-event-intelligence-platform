# ADR-001 — Shipment Core Domain and State Machine

- Status: Accepted
- Date: 2026-09-05
- Reviewed: 2026-09-10; later refinements are identified below.
- Decision: Implement the Core Domain as an infrastructure-independent component, using a `Shipment` entity, an immutable `ShipmentEvent` entity, and an explicit State Machine to control state transitions.

## 1. Context

The Freight Event Intelligence Platform needs a consistent view of each shipment's current state from events originating in different sources. Events may be duplicated, arrive out of order, have different formats, represent state changes or information updates, and later be processed asynchronously.

Phase 1 builds the domain before infrastructure such as PostgreSQL, RabbitMQ, Redis, or FastAPI. This ADR establishes the main domain abstractions so its fundamental rules can be tested independently of infrastructure.

## 2. Problem

We need to define how to represent a Shipment and related events, control state transitions, locate business rules, prevent arbitrary external state changes, distinguish event occurrence from receipt, and test those rules without a database or message broker. Business rules must not be prematurely placed in repositories, consumers, or controllers.

## 3. Decision

The Core Domain is an infrastructure-independent component:

```text
app/domain/shipment/
    entities.py
    events.py
    event_handler.py
    state_machine.py
    exceptions.py
```

Tests are separate under `tests/domain/shipment/`. `Shipment` represents the entity and current state; `ShipmentEvent` represents a received business event; `ShipmentStateMachine` defines allowed transitions; and domain exceptions represent rule violations.

## 4. Shipment

`Shipment` is the main domain entity. Its initial model contains `id`, `reference_number`, `origin`, `destination`, `carrier`, `status`, `created_at`, and `updated_at`. It starts in `CREATED` and is constructed via `Shipment.create(...)`, so external code need not know initialization details.

State changes are coordinated by `ShipmentEventHandler.handle(shipment, event)`
through `shipment.change_status(event_type, occurred_at)`. Location changes use
`shipment.update_location(payload, occurred_at)`. These methods concentrate
business rules inside the domain; there is no current `Shipment.apply_event`
method.

## 5. ShipmentEvent

`ShipmentEvent` contains `event_id`, `shipment_id`, `event_type`, `source`,
`occurred_at`, `received_at`, `payload`, and `processing_status` (added by
ADR-005). Its fields cannot be reassigned, using:

```python
@dataclass(frozen=True, slots=True)
class ShipmentEvent:
    ...
```

Immutability reflects an event's historical nature: an event that happened and was recorded must not be changed to adapt history to current state.

## 6. `occurred_at` and `received_at`

`occurred_at` is when the event actually happened; `received_at` is when the system received it. Receipt order need not equal occurrence order. For example, an event that occurred at 10:05 may be received at 10:06 before an event that occurred at 10:00 and is received at 10:07. The architecture must not assume `received_at order == occurred_at order`.

## 7. State Machine

The lifecycle states are `CREATED`, `SCHEDULED`, `PICKED_UP`, `IN_TRANSIT`, `DELAYED`, and `DELIVERED`:

```text
CREATED    --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED  --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP  --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--------> DELIVERED
DELAYED    --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED    --DELIVERED--------> DELIVERED
```

The transition table lives explicitly in `ShipmentStateMachine`, rather than being scattered as `if`/`elif` logic in the entity. This makes rules explicit, centralized, reviewable, testable, and infrastructure-independent.

## 8. Invalid transitions

An undefined transition raises the domain exception `InvalidStateTransition`. For example, `CREATED -> DELIVERED` is rejected. An invalid transition is a domain-rule violation, not merely a technical failure:

```text
Invalid event -> Domain rejects event -> Shipment state remains unchanged
```

## 9. State Machine responsibility

The State Machine only determines which state may follow the current state for an event type. It does not persist shipments, publish messages, access PostgreSQL or RabbitMQ, retry, detect duplicates, control transactions, or decide how late events are reprocessed. Those responsibilities belong to layers introduced later.

## 10. Tests

Unit tests cover selected valid transitions, invalid transitions (including
transitions from `DELIVERED`), initial state, event application, `updated_at`,
cross-shipment rejection, unchanged status after an invalid transition, and
event field immutability. They are not an exhaustive test of every table entry.

## 11. `SHIPMENT_CREATED`

`SHIPMENT_CREATED` exists in the event catalog but is not a State Machine transition: `Shipment.create()` already establishes `CREATED`. This avoids a redundant `SHIPMENT_CREATED -> CREATED` transition.

ADR-003 later formalizes that `POST /shipments` creates the entity and records the historical `SHIPMENT_CREATED` event in the same use case and persistence transaction. This does not change the decision that it is not a state-machine transition. External event processing rejects `SHIPMENT_CREATED` with `InvalidShipmentEvent`; it is reserved for the internal `CreateShipment` flow.

## 12. State-changing and informational events

Not every event changes state. `LOCATION_UPDATED` updates coordinates without
entering the lifecycle state machine. `SHIPMENT_DEPARTED` is the event that moves
`PICKED_UP` or `DELAYED` to `IN_TRANSIT`. ADR-002 records this refinement of the
initial model.

## 13. Out-of-order events

Out-of-order handling was unresolved in Phase 1. ADR-005 now places the policy
in the domain handler: strictly older lifecycle or location events are retained
as `STORED_OUT_OF_ORDER` without modifying that projection. Non-late lifecycle
events enter the state machine. The handler does not replay history or validate
a late transition against reconstructed historical state. Persistence and
deduplication remain outside the domain.

## 14. Follow-up decisions now implemented

ADR-003 establishes atomic shipment/creation-event persistence. ADR-004 defines
global event identity and HTTP concurrent conflict recovery. ADR-005 defines
independent location and lifecycle timelines. ADR-006 and ADR-007 introduce
RabbitMQ ingestion, retry classification, and DLQ.

The identity association, initial state, explicit transition table, and rejection
of invalid non-late transitions remain domain invariants. No lifecycle transition
leaves `DELIVERED`; location handling remains separate from lifecycle transitions.

## 15. Out of scope

This ADR does not define PostgreSQL, SQLAlchemy, FastAPI, RabbitMQ, Redis, Outbox, retries, dead-letter queues, Prometheus, Grafana, or microservices. Its sole purpose is an infrastructure-independent domain foundation.

## 16. Consequences

The domain remains infrastructure-independent, with explicit rules and fast unit
tests. Separate entities, events, and a handler add structure and mapping work,
but allow HTTP and workers to share behavior. This does not imply Event Sourcing:
the current projection is persisted directly and no historical replay exists.

## 17. Validation and evolution

Domain tests cover initial state, state-machine behavior, event field
immutability, cross-shipment rejection, and late-event handling. The tests do
not establish deep immutability of mutable payload objects. Current validation
results and coverage limits are maintained in [technical context](../context.md).
Future domain changes should refine the existing rules through tests and ADRs,
rather than putting rules into transport or persistence adapters.
