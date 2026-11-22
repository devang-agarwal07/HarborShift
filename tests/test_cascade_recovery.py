from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from harborshift.cascade import DependencyGraph, Task, load_manufacturing
from harborshift.data_loader import Dataset, default_source, load_dataset
from harborshift.disruptions import DisruptionEvent
from harborshift.impact import ShipmentImpact
from harborshift.models import Contract, Port, Route, Shipment, ShipmentLeg, Supplier
from harborshift.recovery import recommend
from harborshift.scenarios import run_scenario
from harborshift.simulation import Simulation


def jan(day):
    return date(2027, 1, day)


@pytest.fixture(scope="module")
def source():
    return load_dataset(default_source(Path(__file__).resolve().parents[1]))


def test_cascade_branches_converges_and_absorbs_slack():
    graph = DependencyGraph([
        Task("root", "Raw", jan(1), 2),
        Task("left", "Fast", jan(3), 1, ("root",)),
        Task("right", "Slow", jan(3), 3, ("root",)),
        Task("join", "Assembly", jan(2), 2, ("left", "right")),
        Task("slack", "Flexible departure", jan(13), 2, ("join",)),
    ])
    baseline = graph.schedule()
    assert baseline["join"].start == jan(6)

    def finish(task, start):
        if task.task_id == "root":
            return jan(5)
        return date.fromordinal(start.toordinal() + task.duration_days)

    revised = graph.schedule(finish)
    assert revised["join"].start == jan(8)
    assert revised["slack"] == baseline["slack"]
    paths = graph.paths_from("root")
    assert {"root", "left", "right", "join", "slack"} == paths.keys()
    assert paths["slack"] == ("root", "left", "join", "slack")


def test_cycle_and_unknown_predecessor_are_rejected():
    with pytest.raises(ValueError, match="cycle"):
        DependencyGraph([Task("a", "A", jan(1), 1, ("b",)), Task("b", "B", jan(1), 1, ("a",))])
    with pytest.raises(ValueError, match="Unknown predecessor"):
        DependencyGraph([Task("a", "A", jan(1), 1, ("missing",))])


def test_end_to_end_manufacturing_disruption_recovery_and_reset(source):
    baseline = run_scenario(source, jan(5), manufacturing=True)
    disrupted = run_scenario(source, jan(5), sample_ids=("E001", "E001"), manufacturing=True)
    assert baseline.cascade[-1].revised.finish == jan(17)
    assert disrupted.cascade[0].direct_delay_days == 2
    assert disrupted.cascade[-1].revised.finish == jan(19)
    assert disrupted.cascade[-1].reason_paths == (("raw", "production", "finished", "delivery"),)
    assert disrupted.urgent_contract_ids == ("DEMO-CUSTOMER",)
    assert disrupted.estimated_penalties_inr == Decimal(5000)
    recovery, = disrupted.recovery
    assert recovery.recommended_id == "DEMO-LOCAL"
    assert not recovery.deadline_feasible
    assert recovery.options[0].handoff_eta == jan(10)
    assert recovery.options[0].eta == jan(19)
    reset = run_scenario(source, jan(5), manufacturing=True)
    assert reset.cascade == baseline.cascade
    assert reset.scenario_id != disrupted.scenario_id
    assert reset.recovery == reset.affected_shipment_ids == ()
    assert "DEMO-LOCAL" not in source.records["suppliers"]


def test_multiple_disruptions_and_manufacturing_safe_local_supplier(source):
    origin = DisruptionEvent("origin", "P03", "strike", jan(1), 4, 4, "closed")
    customer = DisruptionEvent("customer", "P11", "strike", jan(20), 3, 3, "closed")
    result = run_scenario(source, jan(1), events=(origin, customer), manufacturing=True)
    assert result.cascade[-1].revised.finish == jan(23)
    assert ("finished", "delivery") in result.cascade[-1].reason_paths
    recommended = result.recovery[0].options[0]
    assert (recommended.option_id, recommended.handoff_eta, recommended.eta) == (
        "DEMO-LOCAL", jan(2), jan(17),
    )
    assert result.recovery[0].deadline_feasible


@pytest.fixture
def recovery_data():
    data = Dataset()
    tables = data.records
    tables["ports"] = {port: Port(port, port, "Demo") for port in "ABCDE"}
    routes = [
        Route("AB", "A", "B", 1, Decimal(5), 10, "open"),
        Route("BD", "B", "D", 1, Decimal(5), 10, "open"),
        Route("AD", "A", "D", 2, Decimal(100), 10, "open"),
        Route("AC", "A", "C", 2, Decimal(10), 10, "open"),
        Route("CD", "C", "D", 2, Decimal(10), 10, "open"),
    ]
    tables["routes"] = {route.route_id: route for route in routes}
    shipment = Shipment("S", "raw", 10, "A", "D", jan(1), jan(3), "C", "planned")
    tables["shipments"]["S"] = shipment
    tables["contracts"]["C"] = Contract("C", "Customer", "raw", 10, "D", jan(6), Decimal(10))
    tables["shipment_legs"] = {
        ("S", 1): ShipmentLeg("S", 1, "AB", jan(1), jan(2)),
        ("S", 2): ShipmentLeg("S", 2, "BD", jan(2), jan(3)),
    }
    for key, port, product, stock, lead, price, status in (
        ("wrong", "D", "other", 10, 0, 0, "qualified"),
        ("stock", "D", "raw", 9, 0, 0, "qualified"),
        ("cert", "D", "raw", 10, 0, 0, "pending"),
        ("unreachable", "E", "raw", 10, 0, 0, "qualified"),
        ("local", "D", "raw", 10, 4, 1, "qualified"),
    ):
        tables["suppliers"][key] = Supplier(key, key, port, product, stock, lead, Decimal(price), status)
    return data, shipment


def test_recovery_filters_suppliers_and_prioritizes_cost_among_on_time(recovery_data):
    data, shipment = recovery_data
    simulation = Simulation(data)
    simulation.add_event(DisruptionEvent("TEST", "B", "strike", jan(1), 9, 4, "closed"))
    impact, = simulation.run(jan(1)).impacts
    result = recommend(data, simulation.snapshot(), shipment, impact, jan(1), 10, original_purchase_inr=Decimal(10))
    options = {option.option_id: option for option in result.options}
    assert result.recommended_id == "local"
    assert result.deadline_feasible
    assert options["local"].eta > options["reroute-fastest"].eta
    assert options["local"].freight_inr == 0
    assert options["reroute-cheapest"].route_ids == ("AC", "CD")
    assert "wrong product" in options["wrong"].reason
    assert "insufficient stock" in options["stock"].reason
    assert "unqualified" in options["cert"].reason
    assert "No feasible path" in options["unreachable"].reason
    del data.records["suppliers"]["local"]
    reroute = recommend(data, simulation.snapshot(), shipment, impact, jan(1), 10, original_purchase_inr=Decimal(10))
    assert reroute.recommended_id == "reroute-cheapest"


def test_no_recovery_possible_when_capacity_is_insufficient(recovery_data):
    data, shipment = recovery_data
    data.records["suppliers"].clear()
    for key, route in data.records["routes"].items():
        data.records["routes"][key] = replace(route, capacity_containers=1)
    simulation = Simulation(data)
    impact = ShipmentImpact("S", "C", jan(3), jan(5), jan(6), 1, 0, Decimal(10), ())
    result = recommend(data, simulation.snapshot(), shipment, impact, jan(1), 1)
    assert result.recommended_id is None
    assert all(option.status == "rejected" for option in result.options)


def test_fixture_is_independent_of_quarantined_deps(source):
    fixture = load_manufacturing(source)
    assert "D001" not in source.records["production_dependencies"]
    assert list(fixture.graph.tasks) == ["raw", "production", "finished", "delivery"]
    assert fixture.dataset.records["shipments"]["DEMO-RAW"].destination_port_id == "P05"



def test_outbound_recovery_keeps_the_mandatory_factory(source):
    event = DisruptionEvent("output", "P11", "strike", jan(17), 4, 4, "closed")
    result = run_scenario(source, jan(12), events=(event,), manufacturing=True)
    recovery, = result.recovery
    assert recovery.shipment_id == "DEMO-FINISHED"
    assert recovery.recommended_id == "wait"
    assert recovery.options[0].eta == jan(21)
    assert any("bypass mandatory manufacturing" in option.reason for option in recovery.options)


def test_in_transit_reroute_is_conditional(recovery_data):
    data, shipment = recovery_data
    data.records["routes"]["BC"] = Route("BC", "B", "C", 1, Decimal(10), 10, "open")
    simulation = Simulation(data)
    simulation.add_event(DisruptionEvent("later", "D", "strike", jan(20), 2, 4, "closed"))
    impact = ShipmentImpact("S", "C", jan(3), jan(3), jan(6), 3, 0, Decimal(10), ())
    shipped = replace(shipment, status="in_transit")
    result = recommend(data, simulation.snapshot(), shipped, impact, jan(2), 10)
    alternatives = [option for option in result.options if option.kind == "reroute"]
    assert alternatives
    assert all(option.status == "conditional" and "reaching B" in option.reason for option in alternatives)
    assert result.recommended_id not in {option.option_id for option in alternatives}
