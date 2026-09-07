# ADR-001 — Shipment Core Domain and State Machine

- Status: Accepted
- Date: 2026-09-05
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
    state_machine.py
    exceptions.py
```

Tests are separate under `tests/domain/shipment/`. `Shipment` represents the entity and current state; `ShipmentEvent` represents a received business event; `ShipmentStateMachine` defines allowed transitions; and domain exceptions represent rule violations.

## 4. Shipment

`Shipment` is the main domain entity. Its initial model contains `id`, `reference_number`, `origin`, `destination`, `carrier`, `status`, `created_at`, and `updated_at`. It starts in `CREATED` and is constructed via `Shipment.create(...)`, so external code need not know initialization details.

State changes occur through `shipment.apply_event(event)`, not arbitrary assignments such as `shipment.status = ShipmentStatus.DELIVERED`. This concentrates business rules inside the domain.

## 5. ShipmentEvent

`ShipmentEvent` contains `event_id`, `shipment_id`, `event_type`, `source`, `occurred_at`, `received_at`, and `payload`. It is immutable after creation, using an equivalent of:

```python
@dataclass(frozen=True, slots=True)
class ShipmentEvent:
    ...
```

Immutability reflects an event's historical nature: an event that happened and was recorded must not be changed to adapt history to current state.

## 6. `occurred_at` and `received_at`

`occurred_at` is when the event actually happened; `received_at` is when the system received it. Receipt order need not equal occurrence order. For example, an event that occurred at 10:05 may be received at 10:06 before an event that occurred at 10:00 and is received at 10:07. The architecture must not assume `received_at order == occurred_at order`.

## 7. State Machine

The initial lifecycle states are `CREATED`, `SCHEDULED`, `PICKED_UP`, `IN_TRANSIT`, `DELAYED`, and `DELIVERED`:

```text
CREATED    --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED  --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP  --LOCATION_UPDATED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--------> DELIVERED
DELAYED    --LOCATION_UPDATED--> IN_TRANSIT
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

Phase 1 unit tests cover valid transitions (`CREATED -> SCHEDULED`, `SCHEDULED -> PICKED_UP`, `PICKED_UP -> IN_TRANSIT`, delayed and delivered paths), invalid transitions (including transitions from `DELIVERED`), initial state, event application, `updated_at`, rejection of events for another shipment, preservation of state after an invalid transition, and event immutability.

## 11. `SHIPMENT_CREATED`

`SHIPMENT_CREATED` exists in the event catalog but is not a State Machine transition: `Shipment.create()` already establishes `CREATED`. This avoids a redundant `SHIPMENT_CREATED -> CREATED` transition.

ADR-003 later formalizes that `POST /shipments` creates the entity and records the historical `SHIPMENT_CREATED` event in the same use case and persistence transaction. This does not change the decision that it is not a state-machine transition. External event processing rejects `SHIPMENT_CREATED` with `InvalidShipmentEvent`; it is reserved for the internal `CreateShipment` flow.

## 12. State-changing and informational events

Not every event must change state. `LOCATION_UPDATED` may occur repeatedly during a journey and should eventually update location without implying `IN_TRANSIT -> IN_TRANSIT`. The initial implementation simplified this behavior; the domain model must distinguish state-changing from informational events.

## 13. Out-of-order events

Out-of-order handling is deliberately unresolved. Events such as `PICKUP_COMPLETED`, `LOCATION_UPDATED`, and `DELIVERED` may arrive in reverse order. A `DELIVERED` event applied while a shipment is `CREATED` is correctly rejected by the state machine, but the application must later decide whether it is invalid or valid but premature. This policy belongs in the appropriate application/processing layer, not simply in `Shipment`.

## 14. Decisions required before Phase 2

Before introducing PostgreSQL, repositories, and FastAPI, the platform must define `SHIPMENT_CREATED` semantics; separate state-changing from informational events; define late/out-of-order detection, acceptance, rejection, storage, and reprocessing; define what `updated_at` represents; document Shipment invariants; confirm event identity scope; and decide duplicate-event handling.

Important invariants include an immutable shipment ID, `CREATED` as the initial state, rejection of another shipment's events, no return from `DELIVERED` to an operational state, and no state change after an invalid transition. The future idempotency design must account for normal at-least-once delivery, probably following `Event Consumer -> Idempotency Check -> Shipment.apply_event()` and reinforced by the database.

## 15. Out of scope

This ADR does not define PostgreSQL, SQLAlchemy, FastAPI, RabbitMQ, Redis, Outbox, retries, dead-letter queues, Prometheus, Grafana, or microservices. Its sole purpose is an infrastructure-independent domain foundation.

## 16. Consequences

Positive consequences are infrastructure independence, explicit rules, fast unit testing, lower coupling, and incremental infrastructure adoption. Costs are that the model does not yet completely define out-of-order or informational events, may require refactoring before persistence, and will need a more sophisticated state machine as rules are discovered. These costs are acceptable while the rules remain explicit and testable.

## 17. Completion criteria and next ADRs

Phase 1 is complete when Shipment, ShipmentEvent, states, State Machine, valid and invalid transition tests, event immutability, cross-shipment rejection, `SHIPMENT_CREATED` semantics, event categories, out-of-order strategy, `updated_at` semantics, Shipment invariants, global event identity, and idempotency strategy are defined.

Expected follow-up ADRs include idempotency, event identity and deduplication, out-of-order events, PostgreSQL persistence, and RabbitMQ. Numbering may change as decisions are made.

## 18. Summary

The project begins with the domain, not infrastructure. Shipment owns its behavior, ShipmentEvent represents immutable facts, and ShipmentStateMachine explicitly defines allowed transitions. The foundation is deliberately small and testable while advanced questions—state and informational events, ordering, identity/idempotency, and timestamp semantics—are resolved before further infrastructure is added.
