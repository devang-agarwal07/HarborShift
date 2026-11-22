"""Scheduled port-call impact, ETA updates, and contract urgency."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from heapq import heappop, heappush

from .data_loader import Dataset
from .disruptions import NetworkSnapshot
from .graph import TransportGraph
from .models import Shipment, ShipmentLeg


class ItineraryIndex:
    def __init__(self, dataset: Dataset, graph: TransportGraph):
        self.by_shipment: dict[str, list[ShipmentLeg]] = {}
        self.by_route: dict[str, list[ShipmentLeg]] = {}
        self.by_port: dict[str, list[ShipmentLeg]] = {}
        for leg in dataset.records["shipment_legs"].values():
            self.by_shipment.setdefault(leg.shipment_id, []).append(leg)
            self.by_route.setdefault(leg.route_id, []).append(leg)
        for legs in self.by_shipment.values():
            legs.sort(key=lambda leg: leg.leg_sequence)
        for route_id, legs in self.by_route.items():
            route = graph.edge(route_id)
            for port_id in dict.fromkeys((route.from_port_id, route.to_port_id)):
                self.by_port.setdefault(port_id, []).extend(legs)


@dataclass(frozen=True)
class PortCallImpact:
    port_id: str
    route_id: str
    leg_sequence: int
    call_type: str
    call_date: date
    status: str
    event_ids: tuple[str, ...]
    wait_days: int


@dataclass(frozen=True)
class ShipmentImpact:
    shipment_id: str
    contract_id: str
    baseline_eta: date
    revised_eta: date
    deadline: date
    slack_days: int
    late_days: int
    penalty_per_day: Decimal
    calls: tuple[PortCallImpact, ...]

    @property
    def estimated_penalty(self) -> Decimal:
        return self.late_days * self.penalty_per_day


@dataclass(frozen=True)
class SimulationResult:
    as_of: date
    impacts: tuple[ShipmentImpact, ...]
    urgent_contracts: tuple[ShipmentImpact, ...]


def wait_for_port(
    snapshot: NetworkSnapshot, port: str, on: date, transit_days: int = 0,
) -> tuple[int, tuple[str, ...]]:
    """Return the wait and contributing events for a port call."""
    active = snapshot.events_at(port, on)
    applied = {}
    ready = on
    while active:
        closures = [event for event in active if event.port_status == "closed"]
        if closures:
            ready = max(event.end for event in closures)
            applied.update((event.event_id, None) for event in closures)
        else:
            restrictions = [event for event in active if event.event_id not in applied]
            if not restrictions:
                break
            # Concurrent restrictions share the same wait instead of being added.
            ready += timedelta(days=max(snapshot.restriction_wait(event, ready, transit_days) for event in restrictions))
            applied.update((event.event_id, None) for event in restrictions)
        active = snapshot.events_at(port, ready)

    return (ready - on).days, tuple(applied)


def evaluate_call(
    snapshot: NetworkSnapshot, leg: ShipmentLeg, port: str, call_type: str,
    on: date, as_of: date, completed: bool,
) -> PortCallImpact | None:
    active = snapshot.events_at(port, on)
    if not active:
        return None
    if completed or on < as_of:
        return PortCallImpact(
            port, leg.route_id, leg.leg_sequence, call_type, on, "already completed",
            tuple(event.event_id for event in active), 0,
        )

    wait_days, event_ids = wait_for_port(
        snapshot, port, on, (leg.planned_arrival_date - leg.planned_departure_date).days,
    )
    status = "modeled impact" if on == as_of else "possible future exposure"
    return PortCallImpact(
        port, leg.route_id, leg.leg_sequence, call_type, on, status,
        event_ids, wait_days,
    )


def evaluate_shipment(
    shipment: Shipment, legs: list[ShipmentLeg], snapshot: NetworkSnapshot, as_of: date,
) -> tuple[date, tuple[PortCallImpact, ...]]:
    """Propagate port waits through one shipment, letting connections absorb delay."""
    calls = []
    previous_arrival = None
    completed = shipment.status == "delivered"
    for leg in legs:
        route = snapshot.graph.edge(leg.route_id)
        departure = leg.planned_departure_date
        if previous_arrival is not None:
            departure = max(departure, previous_arrival)

        # Arrival and departure at the same port on the same day share one call.
        if departure != previous_arrival:
            call = evaluate_call(snapshot, leg, route.from_port_id, "departure", departure, as_of, completed)
            if call:
                calls.append(call)
                departure += timedelta(days=call.wait_days)

        sailing_time = leg.planned_arrival_date - leg.planned_departure_date
        arrival = departure + sailing_time
        if route.from_port_id != route.to_port_id or sailing_time:
            call = evaluate_call(snapshot, leg, route.to_port_id, "arrival", arrival, as_of, completed)
            if call:
                calls.append(call)
                arrival += timedelta(days=call.wait_days)
        previous_arrival = arrival

    return previous_arrival or shipment.planned_arrival_date, tuple(calls)


def analyze(
    dataset: Dataset, itineraries: ItineraryIndex, snapshot: NetworkSnapshot, as_of: date,
    shipment_id: str | None = None,
) -> SimulationResult:
    candidate_ids = {
        leg.shipment_id
        for event in snapshot.events
        for leg in itineraries.by_port.get(event.port_id, ())
    }
    if shipment_id is not None:
        candidate_ids.intersection_update((shipment_id,))
    impacts = []
    queue = []
    for shipment_id in sorted(candidate_ids):
        shipment = dataset.records["shipments"][shipment_id]
        if shipment.status == "cancelled":
            continue
        eta, calls = evaluate_shipment(shipment, itineraries.by_shipment[shipment_id], snapshot, as_of)
        if not calls:
            continue
        contract = dataset.records["contracts"][shipment.contract_id]
        slack = (contract.deadline - eta).days
        impact = ShipmentImpact(
            shipment_id, contract.contract_id, shipment.planned_arrival_date, eta,
            contract.deadline, slack, max(0, -slack), contract.late_penalty_inr_per_day, calls,
        )
        impacts.append(impact)
        if slack <= 0 and any(call.wait_days for call in calls):
            heappush(queue, (slack, -impact.penalty_per_day, impact.contract_id, shipment_id, impact))

    # Rank each contract once, using its most urgent affected shipment.
    urgent_contracts = []
    seen = set()
    while queue:
        impact = heappop(queue)[-1]
        if impact.contract_id not in seen:
            urgent_contracts.append(impact)
            seen.add(impact.contract_id)

    return SimulationResult(as_of, tuple(impacts), tuple(urgent_contracts))
