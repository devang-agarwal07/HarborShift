from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_dataset
from harborshift.data_loader import Dataset
from harborshift.ml.predict import DelayPrediction, MODEL_PATH, predict_delay
from harborshift.models import Port
from harborshift.news.fetch import collect, parse_feed
from harborshift.scenarios import run_scenario


@pytest.fixture
def ml_features():
    return {
        "port_id": "P11", "event_type": "congestion", "expected_duration_days": 3,
        "severity_1_to_5": 2, "congestion_0_to_5": 1, "planned_transit_days": 5,
        "schedule_buffer_days": 0,
    }


def test_saved_model_handles_unseen_category_and_returns_nonnegative_days(ml_features):
    assert MODEL_PATH.exists()
    regular = predict_delay(ml_features)
    assert regular.source == "synthetic_model"
    assert predict_delay({**ml_features, "event_type": "unseen"}).days >= 0


def test_missing_inputs_invalid_ranges_and_missing_model(ml_features, tmp_path):
    missing_model = tmp_path / "missing.joblib"
    fallback = predict_delay(ml_features, missing_model)
    assert fallback.source == "rule_fallback"
    assert fallback.days == 1
    with pytest.raises(ValueError, match="Missing prediction fields"):
        predict_delay({})
    with pytest.raises(ValueError, match="congestion_0_to_5"):
        predict_delay({**ml_features, "congestion_0_to_5": 6})


def test_synthetic_prediction_replaces_rule_wait(monkeypatch):
    today = date(2027, 1, 18)
    data = get_dataset()
    rule = run_scenario(data, today, sample_ids=("E004",), shipment_id="SH044")
    monkeypatch.setattr("harborshift.scenarios.predict_delay",
                        lambda features: DelayPrediction(2.1, "test", "synthetic_model"))
    forecast = run_scenario(data, today, sample_ids=("E004",), shipment_id="SH044", use_ml=True)
    assert (forecast.impacts[0].revised_eta - today).days == 3
    assert (rule.impacts[0].revised_eta - today).days == 1
    assert forecast.prediction.sources == ("synthetic_model",)
    monkeypatch.setattr("harborshift.scenarios.predict_delay",
                        lambda features: DelayPrediction(42, "test", "rule_fallback"))
    fallback = run_scenario(data, today, sample_ids=("E004",), shipment_id="SH044", use_ml=True)
    assert fallback.impacts == rule.impacts
    assert fallback.prediction.sources == ("rule_fallback",)


def test_api_queries_isolate_scenarios_and_expose_numeric_costs():
    client = TestClient(app)
    assert client.get("/health").json()["shipment_count"] == 100
    assert len(client.get("/ports").json()) == 20
    assert len(client.get("/routes").json()) == 50
    assert len(client.get("/shipments").json()) == 100
    assert len(client.get("/disruptions").json()) == 5
    query = {"as_of": "2027-01-05", "manufacturing": True}
    chosen = client.post("/simulate", json={**query, "sample_ids": ["E001"]})
    assert chosen.status_code == 200
    report = chosen.json()
    assert report["affected_shipment_ids"] == ["DEMO-FINISHED", "DEMO-RAW"]
    assert report["cascade"][-1]["revised"]["finish"] == "2027-01-19"
    assert report["recovery"][0]["options"][0]["total_future_inr"] == 23000
    reset = client.post("/simulate", json=query).json()
    assert reset["scenario_id"] != report["scenario_id"]
    assert reset["events"] == []
    assert reset["cascade"][-1]["revised"]["finish"] == "2027-01-17"


def test_api_invalid_input_and_impossible_route():
    client = TestClient(app)
    query = {"origin": "P11", "destination": "P03", "quantity_units": 10, "units_per_container": 10}
    route = client.post("/route", json=query)
    assert route.status_code == 200
    assert route.json()["no_route_reason"]
    assert client.post("/route", json={**query, "origin": "invalid"}).status_code == 422
    assert client.post("/route", json={**query, "quantity_units": 0}).status_code == 422
    assert client.post("/simulate", json={"as_of": "2027-01-05", "shipment_id": "bad"}).status_code == 422
    assert client.post("/simulate", json={"as_of": "2027-01-05", "congestion": 6}).status_code == 422
    assert client.post("/simulate", json={
        "as_of": "2027-01-05", "event": {
            "port_id": "invalid", "event_type": "strike", "duration_days": 1,
            "severity": 1, "port_status": "closed",
        },
    }).status_code == 422


def test_blocking_dataset_error_returns_503():
    invalid = Dataset()
    invalid.add_finding("routes", "", "file", "CSV missing")
    app.dependency_overrides[get_dataset] = lambda: invalid
    try:
        response = TestClient(app).get("/health")
        assert response.status_code == 503
        assert response.json()["detail"][0]["filename"] == "routes.csv"
    finally:
        app.dependency_overrides.pop(get_dataset)


def test_advisory_replay_is_explicit_and_uses_simulated_date():
    response = TestClient(app).post("/simulate", json={
        "as_of": "2027-01-05",
        "event": {"port_id": "P05", "event_type": "strike", "duration_days": 5,
                  "severity": 4, "port_status": "closed", "advisory_replay": True},
    })
    assert response.status_code == 200
    event = response.json()["events"][0]
    assert event["start"] == "2027-01-05"
    assert event["source"].startswith("advisory replay")


@pytest.fixture
def feed():
    return (Path(__file__).parent / "fixtures" / "advisories.xml").read_bytes()


def test_news_dedup_missing_info_ambiguity_and_failure(feed):
    ports = [Port("P05", "Durban", "South Africa"), Port("P11", "Mumbai", "India")]

    def fetch(url):
        if url == "failed":
            raise TimeoutError("offline")
        return feed

    result = collect(ports, (("A", "ok"), ("Duplicate", "ok"), ("Offline", "failed")), fetch)
    valid, ambiguous = result.articles
    assert valid.url == "https://example.org/durban"
    assert valid.candidate.port_id == "P05"
    assert valid.published == "2026-01-05T12:00:00+00:00"
    assert valid.candidate.duration_days is None
    assert valid.candidate.severity is None
    assert ambiguous.candidate.port_id is None
    assert ambiguous.candidate.matched_ports == ("P05", "P11")
    assert result.errors == ("Offline feed unavailable.",)
    assert run_scenario(get_dataset(), date(2027, 1, 5), manufacturing=True).events == ()


def test_atom_feed_parses_advisory_links():
    atom = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry>
        <title>Port of Durban equipment outage</title><link href='https://example.org/news'/>
        <updated>2026-01-05T12:00:00Z</updated>
        </entry></feed>"""
    result, = parse_feed(atom, "Official test", [Port("P05", "Durban", "South Africa")])
    assert result.candidate.event_type == "equipment_failure"
    assert result.published == "2026-01-05T12:00:00+00:00"
