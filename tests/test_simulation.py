from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from harborshift.data_loader import Dataset
from harborshift.disruptions import DisruptionEvent
from harborshift.models import Contract, Disruption, Port, Route, Shipment, ShipmentLeg
from harborshift.simulation import Simulation
from main import main


def january(day):
    return date(2027, 1, day)


def event(port, start, duration=3, event_id="TEST", status="closed", severity=4):
    return DisruptionEvent(event_id, port, "strike", january(start), duration, severity, status)


@pytest.fixture
def dataset():
    dataset = Dataset()
    records = dataset.records
    records["ports"] = {port: Port(port, port, "Demo") for port in "ABC"}
    records["routes"] = {
        "AB": Route("AB", "A", "B", 5, Decimal("100"), 10, "open"),
        "BC": Route("BC", "B", "C", 4, Decimal("80"), 10, "open"),
    }
    for shipment_id, start, transfer, deadline, penalty in (
        ("S1", 1, 6, 11, 100),
        ("S2", 6, 12, 20, 80),
        ("S3", 1, 6, 11, 200),
    ):
        contract = f"C{shipment_id[-1]}"
        records["shipments"][shipment_id] = Shipment(
            shipment_id, "P", 10, "A", "C", january(start), january(transfer + 4),
            contract, "planned",
        )
        records["shipment_legs"][(shipment_id, 1)] = ShipmentLeg(
            shipment_id, 1, "AB", january(start), january(start + 5),
        )
        records["shipment_legs"][(shipment_id, 2)] = ShipmentLeg(
            shipment_id, 2, "BC", january(transfer), january(transfer + 4),
        )
        records["contracts"][contract] = Contract(
            contract, "Customer", "P", 10, "C", january(deadline), Decimal(penalty),
        )
    records["disruptions"]["E001"] = Disruption(
        "E001", january(6), "B", "strike", 3, 4, "closed", "Synthetic test closure",
    )
    return dataset


def test_disruption_affects_only_port_calls_within_the_window(dataset):
    simulation = Simulation(dataset)
    simulation.add_sample("E001")
    result = simulation.run(january(6))
    assert [impact.shipment_id for impact in result.impacts] == ["S1", "S3"]

    first = result.impacts[0]
    assert first.baseline_eta == january(10)
    assert first.revised_eta == january(13)
    assert first.slack_days == -2
    assert first.estimated_penalty == 200
    assert len(first.calls) == 1
    call = first.calls[0]
    assert (call.port_id, call.route_id, call.call_type) == ("B", "AB", "arrival")
    assert call.status == "modeled impact"
    assert call.wait_days == 3
    assert [impact.contract_id for impact in result.urgent_contracts] == ["C3", "C1"]


@pytest.mark.parametrize(
    ("port", "day", "shipment", "call_type", "revised_eta"),
    [("A", 6, "S2", "departure", 18), ("C", 10, "S1", "arrival", 13)],
)
def test_origin_and_destination_closures(dataset, port, day, shipment, call_type, revised_eta):
    simulation = Simulation(dataset)
    simulation.add_event(event(port, day))
    impact = next(impact for impact in simulation.run(january(day)).impacts
                  if impact.shipment_id == shipment)
    assert impact.calls[0].call_type == call_type
    assert impact.revised_eta == january(revised_eta)


def test_end_boundary_and_ships_at_sea_are_unaffected(dataset):
    simulation = Simulation(dataset)
    simulation.add_event(event("B", 3, duration=3))
    assert simulation.run(january(3)).impacts == ()


def test_future_exposure_and_completed_calls_are_distinct(dataset):
    simulation = Simulation(dataset)
    simulation.add_sample("E001")
    forecast = simulation.run(january(5))
    assert forecast.impacts[0].calls[0].status == "possible future exposure"
    assert forecast.impacts[0].revised_eta == january(13)

    past = simulation.run(january(7))
    assert past.impacts[0].calls[0].status == "already completed"
    assert past.impacts[0].revised_eta == january(10)
    assert past.urgent_contracts == ()


def test_restriction_consumes_slack_and_can_be_absorbed_by_connection(dataset):
    simulation = Simulation(dataset)
    simulation.add_event(event("B", 11, duration=4, status="restricted", severity=2))
    impact, = simulation.run(january(11)).impacts
    assert impact.shipment_id == "S2"
    assert len(impact.calls) == 1
    assert impact.calls[0].wait_days == 1
    assert impact.revised_eta == impact.baseline_eta == january(16)


def test_snapshot_restriction_uses_severity_and_does_not_stack_duplicate_delay(dataset):
    simulation = Simulation(dataset)
    simulation.add_event(event("B", 6, duration=4, status="restricted", severity=3))
    simulation.add_event(event("B", 6, duration=4, event_id="OTHER", status="restricted", severity=5))
    condition = simulation.snapshot().route_condition("AB", january(6))
    assert condition.status == "restricted"
    assert condition.estimated_delay_days == 3
    result = simulation.run(january(6))
    assert result.impacts[0].calls[0].wait_days == 3
    assert result.impacts[0].revised_eta == january(13)


def test_reopening_is_delayed_by_a_contiguous_closure(dataset):
    simulation = Simulation(dataset)
    simulation.add_sample("E001")
    simulation.add_event(event("B", 9, duration=1))
    call = simulation.run(january(6)).impacts[0].calls[0]
    assert call.event_ids == ("E001", "TEST")
    assert call.wait_days == 4


def test_wait_can_expose_a_later_call(dataset):
    simulation = Simulation(dataset)
    simulation.add_sample("E001")
    simulation.add_event(event("C", 13, duration=1))
    impact = simulation.run(january(6)).impacts[0]
    assert [call.port_id for call in impact.calls] == ["B", "C"]
    assert impact.revised_eta == january(14)


def test_duplicate_event_and_reset_preserve_baseline(dataset):
    simulation = Simulation(dataset)
    assert simulation.add_sample("E001")
    original = simulation.run(january(6))
    assert not simulation.add_sample("E001")
    assert simulation.run(january(6)) == original
    with pytest.raises(ValueError, match="Conflicting event ID"):
        simulation.add_event(event("A", 6, event_id="E001"))
    snapshot = simulation.snapshot()
    assert snapshot.route_condition("AB", january(6)).status == "closed"
    assert snapshot.route_condition("AB", january(9)).status == "open"
    simulation.reset()
    assert not simulation.run(january(6)).impacts
    assert snapshot.route_condition("AB", january(6)).status == "closed"
    assert simulation.snapshot().route_condition("AB", january(6)).status == "open"
    assert dataset.records["routes"]["AB"].status == "open"
    assert dataset.records["shipments"]["S1"].planned_arrival_date == january(10)


def test_cancelled_and_delivered_shipments_receive_no_delay(dataset):
    records = dataset.records["shipments"]
    records["S1"] = replace(records["S1"], status="cancelled")
    records["S3"] = replace(records["S3"], status="delivered")
    simulation = Simulation(dataset)
    simulation.add_sample("E001")
    impact, = simulation.run(january(6)).impacts
    assert impact.shipment_id == "S3"
    assert impact.calls[0].status == "already completed"
    assert impact.revised_eta == impact.baseline_eta


def test_simulate_cli_prints_etas_and_ranked_contracts(dataset, monkeypatch, capsys):
    monkeypatch.setattr("main.load_dataset", lambda source: dataset)
    assert main(["simulate", "--event", "E001", "--as-of", "2027-01-06"]) == 0
    output = capsys.readouterr().out
    assert "S1 (C1): ETA 2027-01-10 -> 2027-01-13" in output
    assert "modeled impact: B arrival" in output
    assert output.index("C3 via S3") < output.index("C1 via S1")

    assert main([
        "simulate", "--as-of", "2027-01-10", "--port", "C", "--event-type", "congestion",
        "--duration", "3", "--severity", "2", "--status", "restricted",
    ]) == 0
    assert "Event manual: C restricted" in capsys.readouterr().out
