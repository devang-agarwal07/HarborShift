"""Shared offline workflow for the CLI, API, and dashboard."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import ceil
from uuid import uuid4

from .cascade import CascadeImpact, cascade_schedule, load_manufacturing
from .data_loader import Dataset
from .disruptions import DisruptionEvent
from .impact import ShipmentImpact
from .ml.predict import predict_delay
from .recovery import RecoveryResult, recommend
from .simulation import Simulation


@dataclass(frozen=True)
class PredictionInfo:
    requested: str
    sources: tuple[str, ...]
    versions: tuple[str, ...]
    congestion: int
    buffer_days: int


@dataclass(frozen=True)
class ScenarioReport:
    scenario_id: str
    as_of: date
    manufacturing: bool
    total_shipments: int
    events: tuple[DisruptionEvent, ...]
    affected_port_ids: tuple[str, ...]
    affected_edge_ids: tuple[str, ...]
    affected_shipment_ids: tuple[str, ...]
    impacts: tuple[ShipmentImpact, ...]
    urgent_contract_ids: tuple[str, ...]
    estimated_penalties_inr: Decimal
    cascade: tuple[CascadeImpact, ...]
    customer_deadline: date | None
    recovery: tuple[RecoveryResult, ...]
    prediction: PredictionInfo
    warnings: tuple[str, ...]


def run_scenario(
    source: Dataset, as_of: date, *,
    sample_ids: tuple[str, ...] = (),
    events: tuple[DisruptionEvent, ...] = (),
    shipment_id: str | None = None,
    manufacturing: bool = False,
    units_per_container: int | None = None,
    use_ml: bool = False,
    congestion: int = 0,
    buffer_days: int = 0,
    original_purchase_inr: Decimal | None = None,
) -> ScenarioReport:
    fixture = load_manufacturing(source) if manufacturing else None
    dataset = fixture.dataset if fixture else source
    shipments = dataset.records["shipments"]
    if shipment_id is not None and shipment_id not in shipments:
        raise ValueError(f"Unknown shipment ID: {shipment_id}")
    if manufacturing and shipment_id is not None:
        raise ValueError("Manufacturing scenarios evaluate the complete chain")
    if units_per_container is None:
        units_per_container = fixture.packing if fixture else 10
    if type(units_per_container) is not int or units_per_container <= 0:
        raise ValueError("Units per container must be a positive integer")
    if type(congestion) is not int or not 0 <= congestion <= 5:
        raise ValueError("Congestion must be an integer from 0 to 5")
    if type(buffer_days) is not int or buffer_days < 0:
        raise ValueError("Schedule buffer must be a nonnegative whole number of days")
    if original_purchase_inr is not None and (
        not original_purchase_inr.is_finite() or original_purchase_inr < 0
    ):
        raise ValueError("Original purchase cost must be finite and nonnegative")

    versions = set()
    prediction_sources = set()

    def estimate(event: DisruptionEvent, on: date, transit_days: int) -> int:
        prediction = predict_delay({
            "port_id": event.port_id,
            "event_type": event.event_type,
            "expected_duration_days": event.duration_days,
            "severity_1_to_5": event.severity,
            "congestion_0_to_5": congestion,
            "planned_transit_days": transit_days,
            "schedule_buffer_days": buffer_days,
        })
        versions.add(prediction.version)
        prediction_sources.add(prediction.source)
        if prediction.source == "rule_fallback":
            return event.restriction_days(on)
        return ceil(prediction.days)

    simulation = Simulation(dataset)
    for event_id in sample_ids:
        simulation.add_sample(event_id)
    for event in events:
        simulation.add_event(event)
    snapshot = simulation.snapshot(estimate if use_ml else None)
    result = simulation.run(as_of, snapshot, shipment_id)
    impacts = result.impacts
    live_impacts = tuple(impact for impact in impacts
                         if any(call.status != "already completed" for call in impact.calls))
    relevant_shipment_ids = {impact.shipment_id for impact in live_impacts}
    ranked = result.urgent_contracts
    urgent_ids = tuple(impact.contract_id for impact in ranked)
    total_penalties = sum((impact.estimated_penalty for impact in ranked), Decimal(0))
    cascade = ()
    customer_deadline = None
    recovery = []

    if fixture:
        by_contract = dataset.records["contracts"]
        contract = by_contract[fixture.customer_contract_id]
        customer_deadline = contract.deadline
        cascade = cascade_schedule(fixture, snapshot, as_of)
        delivery = next(task for task in cascade if task.task_id == fixture.delivery_task_id)
        raw = next((impact for impact in live_impacts if impact.shipment_id == fixture.raw_shipment_id), None)
        impacted_tasks = [task for task in cascade if task.revised.finish > task.baseline.finish]
        relevant_shipment_ids.update(
            fixture.graph.tasks[task.task_id].shipment_id
            for task in impacted_tasks
            if fixture.graph.tasks[task.task_id].shipment_id
        )
        if delivery.revised.finish > delivery.baseline.finish and delivery.revised.finish >= contract.deadline:
            urgent_ids = (contract.contract_id,)
            total_penalties = max(0, (delivery.revised.finish - contract.deadline).days) * contract.late_penalty_inr_per_day
        else:
            urgent_ids, total_penalties = (), Decimal(0)

        finished = next((impact for impact in live_impacts if impact.shipment_id == fixture.finished_shipment_id), None)
        target = raw or finished
        if target:
            task_id = fixture.raw_task_id if raw else fixture.finished_task_id

            def downstream(handoff):
                revised = cascade_schedule(fixture, snapshot, as_of, (task_id, handoff))
                return next(task.revised.finish for task in revised if task.task_id == fixture.delivery_task_id)

            purchase = original_purchase_inr
            if raw and purchase is None:
                purchase = fixture.original_purchase_inr
            recovery.append(recommend(
                dataset, snapshot, shipments[target.shipment_id], target, as_of, units_per_container,
                original_purchase_inr=purchase, final_contract=contract, delivery_after_handoff=downstream,
                supplier_replacement_allowed=raw is not None,
            ))
    else:
        for impact in live_impacts:
            recovery.append(recommend(
                dataset, snapshot, shipments[impact.shipment_id], impact, as_of, units_per_container,
                original_purchase_inr=original_purchase_inr,
            ))

    if not prediction_sources:
        prediction_sources.add("rule_fallback")
        versions.add("rule-v1")
    if use_ml and any(event.port_status == "closed" for event in snapshot.events):
        prediction_sources.add("rule_fallback")
        versions.add("rule-v1")
    port_ids = {event.port_id for event in snapshot.events if event.duration_days and event.end > as_of}
    warnings = [f"{finding.filename} [{finding.record_id}]: {finding.issue}"
                for finding in source.findings if finding.severity == "WARNING"]
    warnings.append("Synthetic schedules, costs, and event assumptions. Closures use the reopening rule.")
    if use_ml:
        warnings.append("Only restricted calls can use the synthetic model. Congestion and buffer are scenario assumptions.")
    return ScenarioReport(
        str(uuid4()), as_of, manufacturing, len(shipments), snapshot.events, tuple(sorted(port_ids)),
        tuple(route.route_id for route in snapshot.graph.edges
              if route.from_port_id in port_ids or route.to_port_id in port_ids),
        tuple(sorted(relevant_shipment_ids)), impacts, urgent_ids, total_penalties, cascade,
        customer_deadline, tuple(recovery), PredictionInfo(
            "synthetic_model" if use_ml else "rule_fallback", tuple(sorted(prediction_sources)),
            tuple(sorted(versions)), congestion, buffer_days,
        ), tuple(warnings),
    )
