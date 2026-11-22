"""Evaluate and rank wait, reroute, and full-quantity sourcing options."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .data_loader import Dataset
from .disruptions import NetworkSnapshot
from .impact import ShipmentImpact, wait_for_port
from .models import Contract, Shipment
from .routing import find_route


@dataclass(frozen=True)
class RecoveryOption:
    option_id: str
    kind: str
    status: str
    reason: str
    eta: date | None = None
    handoff_eta: date | None = None
    route_ids: tuple[str, ...] = ()
    freight_inr: Decimal | None = None
    purchase_inr: Decimal | None = None
    penalty_inr: Decimal | None = None
    total_future_inr: Decimal | None = None
    late_days: int | None = None
    lead_days: int | None = None
    required_containers: int | None = None


@dataclass(frozen=True)
class RecoveryResult:
    shipment_id: str
    contract_id: str
    options: tuple[RecoveryOption, ...]
    recommended_id: str | None
    deadline_feasible: bool
    warnings: tuple[str, ...]


def recommend(
    dataset: Dataset,
    snapshot: NetworkSnapshot,
    shipment: Shipment,
    impact: ShipmentImpact,
    as_of: date,
    units_per_container: int,
    *,
    original_purchase_inr: Decimal | None = None,
    final_contract: Contract | None = None,
    delivery_after_handoff: Callable[[date], date] | None = None,
    supplier_replacement_allowed: bool = True,
) -> RecoveryResult:
    """Rank one shipment's options, optionally through a required downstream chain."""
    if type(units_per_container) is not int or units_per_container <= 0:
        raise ValueError("Units per container must be a positive integer")
    if original_purchase_inr is not None and (
        not original_purchase_inr.is_finite() or original_purchase_inr < 0
    ):
        raise ValueError("Original purchase cost must be finite and nonnegative")
    contract = final_contract or dataset.records["contracts"][shipment.contract_id]
    graph = snapshot.graph
    containers = (shipment.quantity_units + units_per_container - 1) // units_per_container
    legs = sorted(
        (leg for leg in dataset.records["shipment_legs"].values() if leg.shipment_id == shipment.shipment_id),
        key=lambda leg: leg.leg_sequence,
    )
    wait_route_ids = tuple(leg.route_id for leg in legs)
    remaining = [graph.edge(leg.route_id) for leg in legs if leg.planned_departure_date >= as_of]
    options = []

    def candidate(option_id, kind, reason, handoff, routes, freight, purchase, lead=None,
                  status="feasible"):
        eta = delivery_after_handoff(handoff) if delivery_after_handoff else handoff
        late = max(0, (eta - contract.deadline).days)
        penalty = contract.late_penalty_inr_per_day * late
        return RecoveryOption(
            option_id, kind, status, reason, eta, handoff, tuple(routes), freight, purchase,
            penalty, freight + purchase + penalty if purchase is not None else None, late,
            lead, containers,
        )

    def rejected(option_id, kind, reason):
        options.append(RecoveryOption(option_id, kind, "rejected", reason))

    if shipment.status in {"cancelled", "delivered"} or impact.baseline_eta < as_of:
        return RecoveryResult(
            shipment.shipment_id, contract.contract_id, (), None, False,
            ("Shipment has no remaining modeled transport.",),
        )

    if any(route.status == "closed" or route.capacity_containers < containers for route in remaining):
        rejected("wait", "wait", "A remaining baseline route is closed or lacks capacity in source data.")
    else:
        freight = containers * sum((route.cost_inr_per_container for route in remaining), Decimal(0))
        options.append(candidate(
            "wait", "wait", "Keep the itinerary and use the modeled wait at affected port calls.",
            impact.revised_eta, wait_route_ids, freight, original_purchase_inr,
        ))

    horizon = max(as_of, contract.deadline, impact.revised_eta)
    closed_ports = {
        event.port_id for event in snapshot.events
        if event.port_status == "closed" and event.duration_days > 0
        and event.start <= horizon and event.end > as_of
    }
    restricted_ports = {
        event.port_id for event in snapshot.events
        if event.port_status == "restricted" and event.duration_days > 0
        and event.start <= horizon and event.end > as_of
    }
    # Treat closures and restrictions as temporarily unavailable for new paths
    # rather than promising an ETA that ignores their waits.
    blocked_ports = closed_ports | restricted_ports
    in_transit = shipment.status == "in_transit" or shipment.departure_date < as_of
    decision_port = shipment.origin_port_id
    decision_date = max(as_of, shipment.departure_date)
    next_leg = None
    if in_transit:
        next_leg = next((leg for leg in legs if leg.planned_arrival_date >= as_of), None)
        if next_leg:
            decision_port = graph.edge(next_leg.route_id).to_port_id
            decision_date = max(as_of, next_leg.planned_arrival_date) + timedelta(
                days=sum(call.wait_days for call in impact.calls
                         if call.leg_sequence <= next_leg.leg_sequence)
            )

    if in_transit and (next_leg is None or decision_port == shipment.destination_port_id):
        rejected("reroute", "reroute", "No intermediate decision point remains in the modeled itinerary.")
    else:
        seen_paths = {wait_route_ids} if not in_transit else set()
        for objective in ("fastest", "cheapest"):
            path = find_route(
                graph, decision_port, shipment.destination_port_id,
                quantity_units=shipment.quantity_units, units_per_container=units_per_container,
                objective=objective, closed_ports=blocked_ports,
            )
            if not path.found:
                rejected(f"reroute-{objective}", "reroute", path.no_route_reason)
                break
            if path.route_ids in seen_paths:
                continue
            seen_paths.add(path.route_ids)
            options.append(candidate(
                f"reroute-{objective}", "reroute",
                f"Conditional on reaching {decision_port} as scheduled and confirming vessel position."
                if in_transit else f"{objective.title()} distinct path from {decision_port}.",
                decision_date + timedelta(days=path.total_days), path.route_ids,
                path.freight_inr, original_purchase_inr,
                status="conditional" if in_transit else "feasible",
            ))
        if len(seen_paths) == 1 and wait_route_ids in seen_paths and not any(
            option.kind == "reroute" for option in options
        ):
            rejected("reroute", "reroute", "The fastest and cheapest feasible paths match the baseline.")

    if not supplier_replacement_allowed:
        rejected("supplier", "supplier", "Replacing finished parts would bypass mandatory manufacturing.")
    suppliers = dataset.records["suppliers"].values() if supplier_replacement_allowed else ()
    for supplier in suppliers:
        option_id = supplier.supplier_id
        reasons = []
        if supplier.product_id != shipment.product_id:
            reasons.append("wrong product")
        if supplier.qualification_status != "qualified":
            reasons.append("supplier is unqualified")
        if supplier.available_units < shipment.quantity_units:
            reasons.append("insufficient stock")
        if reasons:
            rejected(option_id, "supplier", f"{supplier.supplier_name}: " + ", ".join(reasons))
            continue

        ready = as_of + timedelta(days=supplier.lead_time_days)
        if supplier.port_id == shipment.destination_port_id:
            # Local delivery has zero sea freight, with the same port-service assumptions.
            wait, _ = wait_for_port(snapshot, supplier.port_id, ready)
            eta = ready + timedelta(days=wait)
            routes, freight = (), Decimal(0)
        else:
            path = find_route(
                graph, supplier.port_id, shipment.destination_port_id,
                quantity_units=shipment.quantity_units, units_per_container=units_per_container,
                objective="cheapest", closed_ports=blocked_ports,
            )
            fastest = find_route(
                graph, supplier.port_id, shipment.destination_port_id,
                quantity_units=shipment.quantity_units, units_per_container=units_per_container,
                objective="fastest", closed_ports=blocked_ports,
            )
            if not path.found:
                rejected(option_id, "supplier", f"{supplier.supplier_name}: {path.no_route_reason}")
                continue
            purchase = supplier.unit_price_inr * shipment.quantity_units
            variants = [path]
            if fastest.route_ids != path.route_ids:
                variants.append(fastest)
            for index, route in enumerate(variants):
                options.append(candidate(
                    option_id if index == 0 else f"{option_id}-fastest", "supplier",
                    f"{supplier.supplier_name}: qualified for the full quantity.",
                    ready + timedelta(days=route.total_days), route.route_ids,
                    route.freight_inr, purchase, supplier.lead_time_days,
                ))
            continue

        options.append(candidate(
            option_id, "supplier", f"{supplier.supplier_name}: local, qualified and full quantity.",
            eta, routes, freight, supplier.unit_price_inr * shipment.quantity_units,
            supplier.lead_time_days,
        ))

    warnings = [
        "Totals are estimated future costs. Existing commitments and cancellation fees are unknown.",
        "New routes conservatively avoid closed or restricted ports during the comparison horizon.",
    ]
    if delivery_after_handoff:
        warnings.append("All options retain production and finished delivery. Common downstream freight is excluded.")
    feasible = [option for option in options if option.status == "feasible"]
    mixed_basis = (
        any(option.total_future_inr is None for option in feasible)
        and any(option.total_future_inr is not None for option in feasible)
    )
    if mixed_basis:
        warnings.append("Purchase costs are incomplete. ETA replaces cost for cross-option ranking.")
    elif feasible and feasible[0].total_future_inr is None:
        warnings.append("Purchase cost is unknown. Common purchase cost is excluded from transport comparison.")

    def rank(option):
        cost = Decimal(0) if mixed_basis else option.total_future_inr
        if cost is None:
            cost = option.freight_inr + option.penalty_inr
        return (option.late_days > 0, option.penalty_inr, cost, option.eta,
                option.kind != "wait", option.option_id)

    ranked = sorted(feasible, key=rank)
    others = [option for option in options if option.status != "feasible"]
    return RecoveryResult(
        shipment.shipment_id, contract.contract_id, tuple(ranked + others),
        ranked[0].option_id if ranked else None,
        any(option.late_days == 0 for option in ranked), tuple(warnings),
    )
