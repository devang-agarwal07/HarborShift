"""Dependency DAG scheduling and the derived manufacturing scenario."""

import json
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .data_loader import Dataset, validate_references, validate_shipments
from .disruptions import NetworkSnapshot
from .impact import evaluate_shipment
from .models import Contract, Shipment, ShipmentLeg, Supplier


FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "manufacturing.json"


@dataclass(frozen=True)
class Task:
    task_id: str
    label: str
    planned_start: date
    duration_days: int
    predecessors: tuple[str, ...] = ()
    shipment_id: str | None = None
    contract_id: str | None = None


@dataclass(frozen=True)
class Timing:
    start: date
    finish: date


class DependencyGraph:
    def __init__(self, tasks: Iterable[Task]):
        self.tasks = {}
        for task in tasks:
            if task.task_id in self.tasks:
                raise ValueError(f"Duplicate task: {task.task_id}")
            if task.duration_days < 0:
                raise ValueError(f"Negative duration: {task.task_id}")
            if len(set(task.predecessors)) != len(task.predecessors):
                raise ValueError(f"Duplicate predecessor: {task.task_id}")
            self.tasks[task.task_id] = task

        self.children = {key: [] for key in self.tasks}
        indegree = {}
        for task in self.tasks.values():
            indegree[task.task_id] = len(task.predecessors)
            for predecessor in task.predecessors:
                if predecessor not in self.tasks:
                    raise ValueError(f"Unknown predecessor: {predecessor}")
                self.children[predecessor].append(task.task_id)

        ready = deque(key for key, degree in indegree.items() if degree == 0)
        order = []
        while ready:
            key = ready.popleft()
            order.append(key)
            for child in self.children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(order) != len(self.tasks):
            raise ValueError("Dependency graph contains a cycle")
        self.order = tuple(order)

    def paths_from(self, start: str) -> dict[str, tuple[str, ...]]:
        paths = {start: (start,)}
        queue = deque([start])
        while queue:
            key = queue.popleft()
            for child in self.children[key]:
                if child not in paths:
                    paths[child] = (*paths[key], child)
                    queue.append(child)
        return paths

    def schedule(self, finish_task: Callable[[Task, date], date] | None = None) -> dict[str, Timing]:
        times = {}
        for key in self.order:
            task = self.tasks[key]
            earliest = [task.planned_start]
            earliest.extend(times[p].finish for p in task.predecessors)
            start = max(earliest)
            finish = finish_task(task, start) if finish_task else start + timedelta(days=task.duration_days)
            if finish < start:
                raise ValueError(f"Task {key} finishes before it starts")
            times[key] = Timing(start, finish)
        return times


@dataclass(frozen=True)
class ManufacturingFixture:
    dataset: Dataset
    graph: DependencyGraph
    raw_shipment_id: str
    raw_task_id: str
    finished_shipment_id: str
    finished_task_id: str
    customer_contract_id: str
    delivery_task_id: str
    packing: int
    original_purchase_inr: Decimal


def load_manufacturing(source: Dataset) -> ManufacturingFixture:
    source.require_valid()
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dataset = Dataset()
    for table in ("ports", "routes", "products", "suppliers", "disruptions"):
        dataset.records[table] = source.records[table].copy()
    supplier = spec["local_supplier"]
    supplier_id = supplier["supplier_id"]
    if supplier_id in dataset.records["suppliers"]:
        raise ValueError(f"Demo supplier ID conflicts with source: {supplier_id}")
    dataset.records["suppliers"][supplier_id] = Supplier(
        **{**supplier, "unit_price_inr": Decimal(supplier["unit_price_inr"])}
    )

    for item in spec["shipments"]:
        shipment_id = item["shipment_id"]
        route = dataset.records["routes"].get(item["route_id"])
        if route is None:
            raise ValueError(f"Manufacturing demo requires source route {item['route_id']}")
        start = date.fromisoformat(item["date"])
        end = start + timedelta(days=route.transit_days)
        contract_id = item["contract_id"]
        dataset.records["shipments"][shipment_id] = Shipment(
            shipment_id, item["product_id"], item["quantity_units"], item["origin_port_id"],
            item["destination_port_id"], start, end, contract_id, "planned",
        )
        dataset.records["shipment_legs"][(shipment_id, 1)] = ShipmentLeg(
            shipment_id, 1, route.route_id, start, end,
        )
        dataset.records["contracts"][contract_id] = Contract(
            contract_id, "Demo customer" if item["late_penalty_inr_per_day"] else "Durban factory",
            item["product_id"], item["quantity_units"], item["destination_port_id"],
            date.fromisoformat(item["deadline"]), Decimal(item["late_penalty_inr_per_day"]),
        )

    validate_references(dataset)
    validate_shipments(dataset)
    dataset.require_valid()
    graph = DependencyGraph(
        Task(**{**item, "planned_start": date.fromisoformat(item["planned_start"]),
                "predecessors": tuple(item["predecessors"])})
        for item in spec["tasks"]
    )
    production = spec["production"]
    raw = dataset.records["shipments"][production["input_shipment_id"]]
    finished = dataset.records["shipments"][production["output_shipment_id"]]
    if (raw.destination_port_id != production["port_id"]
            or finished.origin_port_id != production["port_id"]
            or raw.product_id != production["input_product_id"]
            or finished.product_id != production["output_product_id"]):
        raise ValueError("Manufacturing fixture has inconsistent product or port links")
    for task in graph.tasks.values():
        if task.shipment_id:
            shipment = dataset.records["shipments"][task.shipment_id]
            elapsed = (shipment.planned_arrival_date - shipment.departure_date).days
            if task.planned_start != shipment.departure_date or task.duration_days != elapsed:
                raise ValueError(f"Task schedule disagrees with its shipment: {task.task_id}")
    raw_task = next(task for task in graph.tasks.values() if task.shipment_id == raw.shipment_id)
    output_task = next(task for task in graph.tasks.values() if task.shipment_id == finished.shipment_id)
    delivery = next(task for task in graph.tasks.values() if task.contract_id == finished.contract_id)
    factory = graph.tasks[production["task_id"]]
    if (factory.task_id not in graph.paths_from(raw_task.task_id)
            or output_task.task_id not in graph.paths_from(factory.task_id)
            or delivery.task_id not in graph.paths_from(output_task.task_id)):
        raise ValueError("Manufacturing fixture must link raw shipment, production, output and delivery")
    return ManufacturingFixture(
        dataset, graph, raw.shipment_id, raw_task.task_id, finished.shipment_id, output_task.task_id,
        finished.contract_id,
        delivery.task_id, spec["packing_units_per_container"], Decimal(spec["original_raw_purchase_inr"]),
    )


@dataclass(frozen=True)
class CascadeImpact:
    task_id: str
    label: str
    baseline: Timing
    revised: Timing
    direct_delay_days: int
    reason_paths: tuple[tuple[str, ...], ...]


def cascade_schedule(
    fixture: ManufacturingFixture, snapshot: NetworkSnapshot, as_of: date,
    replacement: tuple[str, date] | None = None,
) -> tuple[CascadeImpact, ...]:
    direct_delays = {}
    baseline = fixture.graph.schedule()

    def finish(task: Task, start: date) -> date:
        planned_finish = start + timedelta(days=task.duration_days)
        if replacement and task.task_id == replacement[0]:
            return max(start, replacement[1])
        if not task.shipment_id:
            return planned_finish
        shipment = fixture.dataset.records["shipments"][task.shipment_id]
        leg = fixture.dataset.records["shipment_legs"][(shipment.shipment_id, 1)]
        shifted = replace(leg, planned_departure_date=start, planned_arrival_date=planned_finish)
        eta, _ = evaluate_shipment(shipment, [shifted], snapshot, as_of)
        if eta > planned_finish:
            direct_delays[task.task_id] = (eta - planned_finish).days
        return eta

    revised = fixture.graph.schedule(finish)
    paths = [fixture.graph.paths_from(key) for key in direct_delays]
    return tuple(
        CascadeImpact(
            key, fixture.graph.tasks[key].label, baseline[key], revised[key],
            direct_delays.get(key, 0), tuple(path[key] for path in paths if key in path),
        )
        for key in fixture.graph.order
    )
