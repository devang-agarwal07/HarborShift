from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from harborshift.data_loader import Dataset
from harborshift.graph import GraphSummary, TransportGraph
from harborshift.models import Port, Route
from main import main


@pytest.fixture
def dataset():
    dataset = Dataset()
    dataset.records["ports"] = {
        "A": Port("A", "Alpha", "USA"),
        "B": Port("B", "Beta", "India"),
        "C": Port("C", "Isolated", "South Africa"),
    }
    dataset.records["routes"] = {
        "R1": Route("R1", "A", "B", 7, Decimal("100.25"), 12, "open"),
        "R2": Route("R2", "A", "B", 3, Decimal("180"), 6, "closed"),
    }
    return dataset


def test_routes_are_directed_and_parallel_edges_are_preserved(dataset):
    graph = TransportGraph(dataset)
    assert tuple(route.route_id for route in graph.neighbors("A")) == ("R1", "R2")
    assert graph.neighbors("B") == ()
    assert graph.edge("R1").cost_inr_per_container == Decimal("100.25")
    assert graph.edge("R2").status == "closed"


def test_isolated_port_is_included(dataset):
    graph = TransportGraph(dataset)
    assert graph.port("C").port_name == "Isolated"
    assert graph.neighbors("C") == ()
    assert graph.summary == GraphSummary(port_count=3, route_count=2)
    with pytest.raises(KeyError):
        graph.neighbors("unknown")


def test_graph_preserves_explicit_reverse_edge(dataset):
    reverse_route = Route("R3", "B", "A", 5, Decimal("100"), 8, "open")
    dataset.records["routes"]["R3"] = reverse_route
    assert TransportGraph(dataset).neighbors("B") == (reverse_route,)


def test_graph_has_a_read_only_summary_and_snapshots_its_indexes(dataset):
    graph = TransportGraph(dataset)
    dataset.records["routes"].clear()
    dataset.records["ports"].clear()
    assert graph.port("C").port_name == "Isolated"
    assert graph.edge("R1") == graph.neighbors("A")[0]
    assert graph.summary == GraphSummary(port_count=3, route_count=2)
    with pytest.raises(FrozenInstanceError):
        graph.summary.route_count = 0


def test_graph_rejects_blocking_validation_errors(dataset):
    dataset.add_finding("routes", "R1", "to_port_id", "unknown destination")
    with pytest.raises(ValueError, match="blocking errors"):
        TransportGraph(dataset)


def test_neighbors_command(dataset, monkeypatch, capsys):
    monkeypatch.setattr("main.load_dataset", lambda source: dataset)
    assert main(["neighbors", "A", "--data", "sample.zip"]) == 0
    output = capsys.readouterr().out
    assert "3 ports, 2 routes" in output
    assert "Alpha (A)" in output
    assert "R1 -> Beta (B): 7 days, 100.25 INR/container" in output
    assert main(["neighbors", "C", "--data", "sample.zip"]) == 0
    assert "No outgoing routes" in capsys.readouterr().out
    assert main(["neighbors", "unknown", "--data", "sample.zip"]) == 1
    assert "Unknown port ID: unknown" in capsys.readouterr().err
