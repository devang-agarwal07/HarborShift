from decimal import Decimal

import pytest

from harborshift.data_loader import Dataset
from harborshift.graph import TransportGraph
from harborshift.models import Port, Route
from harborshift.routing import find_route
from main import main


@pytest.fixture
def dataset():
    data = Dataset()
    data.records["ports"] = {
        port_id: Port(port_id, port_id, "Demo") for port_id in "ABCDE"
    }
    routes = [
        Route("R1", "A", "B", 9, Decimal("50"), 8, "open"),
        Route("R2", "A", "C", 1, Decimal("30"), 8, "open"),
        Route("R3", "C", "B", 1, Decimal("30"), 2, "open"),
        Route("R4", "B", "D", 2, Decimal("70"), 8, "restricted"),
        Route("R5", "A", "D", 12, Decimal("12.75"), 8, "open"),
        Route("R6", "A", "C", 4, Decimal("1"), 1, "open"),
        Route("R7", "C", "D", 0, Decimal("0"), 8, "closed"),
        Route("R8", "B", "C", 0, Decimal("0"), 8, "open"),
    ]
    data.records["routes"] = {route.route_id: route for route in routes}
    return data


@pytest.fixture
def graph(dataset):
    return TransportGraph(dataset)


def test_fastest_and_cheapest_have_independent_weights(graph):
    fastest = find_route(graph, "A", "D", quantity_units=11, units_per_container=10)
    assert fastest.found
    assert fastest.port_ids == ("A", "C", "B", "D")
    assert fastest.route_ids == ("R2", "R3", "R4")
    assert fastest.total_days == 4
    assert fastest.freight_inr == Decimal("260")

    cheapest = find_route(
        graph, "A", "D", quantity_units=11, units_per_container=10, objective="cheapest"
    )
    assert cheapest.port_ids == ("A", "D")
    assert cheapest.route_ids == ("R5",)
    assert cheapest.total_days == 12
    assert cheapest.freight_inr == Decimal("25.50")


@pytest.mark.parametrize(("start", "end"), [("A", "E"), ("D", "A")])
def test_unreachable_or_wrong_direction(graph, start, end):
    result = find_route(graph, start, end, quantity_units=1, units_per_container=1)
    assert not result.found
    assert result.no_route_reason == f"No feasible path from {start} to {end}"
    assert result.total_days is None
    assert result.freight_inr is None
    assert result.route_ids == result.port_ids == ()


def test_same_port_needs_no_transport(graph):
    result = find_route(graph, "E", "E", quantity_units=1, units_per_container=1)
    assert result.found
    assert result.port_ids == ("E",)
    assert result.route_ids == ()
    assert result.total_days == result.freight_inr == 0


def test_closed_port_changes_route_and_leaves_baseline_intact(graph):
    result = find_route(graph, "A", "D", quantity_units=10, units_per_container=10, closed_ports={"B"})
    assert result.route_ids == ("R5",)
    exclusions = {edge.route_id: edge.reasons for edge in result.excluded_edges}
    assert exclusions["R3"] == ("port B is closed",)
    assert exclusions["R4"] == ("port B is closed",)
    assert exclusions["R7"] == ("marked closed in route data",)

    baseline = find_route(graph, "A", "D", quantity_units=10, units_per_container=10)
    assert baseline.route_ids == ("R2", "R3", "R4")


@pytest.mark.parametrize("closed_port", ["A", "B", "D"])
def test_closing_an_endpoint_or_required_stop_makes_route_infeasible(graph, closed_port):
    result = find_route(
        graph, "A", "D", quantity_units=10, units_per_container=10,
        required_stops=("B",), closed_ports={closed_port},
    )
    assert not result.found
    assert result.no_route_reason == f"Required port {closed_port} is closed"


def test_route_closure_uses_feasible_parallel_edge(graph):
    result = find_route(graph, "A", "C", quantity_units=1, units_per_container=1, closed_routes={"R2"})
    assert result.route_ids == ("R6",)
    reasons = {edge.route_id: edge.reasons for edge in result.excluded_edges}
    assert reasons["R2"] == ("closed in this snapshot",)


def test_ceiling_packing_excludes_routes_with_insufficient_capacity(graph):
    result = find_route(graph, "A", "D", quantity_units=21, units_per_container=10)
    assert result.required_containers == 3
    assert result.route_ids == ("R1", "R4")
    reasons = {edge.route_id: edge.reasons for edge in result.excluded_edges}
    assert reasons["R3"] == ("capacity 2 below 3 required",)

    full = find_route(graph, "A", "D", quantity_units=81, units_per_container=10)
    assert full.required_containers == 9
    assert not full.found


def test_cheapest_route_preserves_ordered_stops(graph):
    result = find_route(
        graph, "A", "D", quantity_units=1, units_per_container=1,
        objective="cheapest", required_stops=("C", "B"),
    )
    assert result.port_ids == ("A", "C", "B", "D")
    assert result.route_ids == ("R6", "R3", "R4")
    assert result.freight_inr == Decimal("101")


@pytest.mark.parametrize(
    ("quantity", "packing", "message"),
    [(0, 1, "quantity_units"), (1, 0, "units_per_container"), (1, 1.5, "units_per_container")],
)
def test_rejects_invalid_packing(graph, quantity, packing, message):
    with pytest.raises(ValueError, match=message):
        find_route(graph, "A", "D", quantity_units=quantity, units_per_container=packing)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"required_stops": ("missing",)}, "Unknown port ID: missing"),
        ({"closed_ports": {"missing"}}, "Unknown port ID: missing"),
        ({"closed_routes": {"missing"}}, "Unknown route ID: missing"),
    ],
)
def test_rejects_unknown_stop_or_closure(graph, options, message):
    with pytest.raises(ValueError, match=message):
        find_route(graph, "A", "D", quantity_units=1, units_per_container=1, **options)


def test_route_cli_compares_the_same_required_stops(dataset, monkeypatch, capsys):
    monkeypatch.setattr("main.load_dataset", lambda source: dataset)
    assert main([
        "route", "A", "D", "--quantity", "10", "--units-per-container", "10",
        "--via", "B", "--close-port", "B",
    ]) == 0
    output = capsys.readouterr().out
    assert "Required stops in order: B" in output
    assert "Route IDs: R2, R3, R4" in output
    assert "Transit: 4 days" in output
    assert "Conservative static scenario" in output
    assert "No route. Required port B is closed." in output
