import csv
from dataclasses import fields
from datetime import date
from decimal import Decimal
from zipfile import ZipFile

import pytest

from harborshift.data_loader import TABLES, load_dataset
from main import main


@pytest.fixture
def data(tmp_path):
    rows = {
        "ports": [
            ("P01", "New York", "USA"),
            ("P05", "Durban", "South Africa"),
            ("P11", "Mumbai", "India"),
        ],
        "routes": [("R01", "P05", "P11", 4, "1400.25", 10, "open")],
        "products": [
            ("PR01", "Steel blanks", "raw_material"),
            ("PR03", "Parts", "finished_part"),
        ],
        "suppliers": [("S01", "Supplier", "P01", "PR01", 40, 2, 100, "qualified")],
        "shipments": [
            ("SH001", "PR03", 10, "P05", "P11", "2027-01-09", "2027-01-13", "C001", "planned"),
        ],
        "shipment_legs": [("SH001", 1, "R01", "2027-01-09", "2027-01-13")],
        "contracts": [("C001", "Customer", "PR03", 10, "P11", "2027-01-15", 1000)],
        "production_dependencies": [("D001", "P01", "PR01", "P05", "PR03", 3, "SH001")],
        "disruptions": [("E001", "2027-01-05", "P05", "strike", 2, 4, "closed", "Demo strike")],
        "historical_delays_synthetic": [("H001", "P05", "strike", 2, 4, 3, 4, 1, "2.5", "synthetic")],
    }
    for table, model in TABLES.items():
        with (tmp_path / f"{table}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(field.name for field in fields(model))
            writer.writerows(rows[table])
    return tmp_path


def replace_value(data, filename, old, new):
    path = data / filename
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_valid_fixture(data, capsys):
    dataset = load_dataset(data)
    dataset.require_valid()
    assert dataset.findings == []
    assert dataset.records["shipments"]["SH001"].departure_date == date(2027, 1, 9)
    assert dataset.records["routes"]["R01"].cost_inr_per_container == Decimal("1400.25")
    assert dataset.records["shipment_legs"][("SH001", 1)].route_id == "R01"
    assert main(["validate", "--data", str(data)]) == 0
    assert "0 errors, 0 warnings" in capsys.readouterr().out


def test_missing_required_csv(data, capsys):
    (data / "routes.csv").unlink()
    assert main(["validate", "--data", str(data)]) == 1
    assert "ERROR: routes.csv file: CSV missing" in capsys.readouterr().out
    with pytest.raises(ValueError, match="blocking errors"):
        load_dataset(data).require_valid()


def test_duplicate_id(data):
    with (data / "ports.csv").open("a", encoding="utf-8") as stream:
        stream.write("P01,Duplicate,USA\n")
    dataset = load_dataset(data)
    assert not dataset.is_valid
    assert dataset.records["ports"]["P01"].port_name == "New York"
    assert any(f.row == 5 and f.issue == "duplicate ID" for f in dataset.findings)


@pytest.mark.parametrize(
    ("filename", "old", "new", "field"),
    [
        ("routes.csv", "R01,P05,P11", "R01,P99,P11", "from_port_id"),
        ("shipments.csv", "2027-01-09", "2027-02-30", "departure_date"),
        ("routes.csv", "1400.25", "-1", "cost_inr_per_container"),
        ("routes.csv", ",open", ",unknown", "status"),
        ("shipment_legs.csv", "SH001,1,", "SH001,2,", "leg_sequence"),
        ("shipments.csv", "PR03,10,", "PR03,11,", "quantity_units"),
        ("routes.csv", "R01,P05,P11", "R01,P01,P11", "origin_port_id"),
        ("shipment_legs.csv", "2027-01-13", "2027-01-08", "planned_arrival_date"),
    ],
)
def test_invalid_records(data, filename, old, new, field):
    replace_value(data, filename, old, new)
    dataset = load_dataset(data)
    assert not dataset.is_valid
    assert any(f.field == field and f.severity == "ERROR" for f in dataset.findings)


def test_invalid_dependency_is_quarantined(data):
    replace_value(data, "production_dependencies.csv", "P05,PR03", "P01,PR01")
    dataset = load_dataset(data)
    assert dataset.is_valid
    assert dataset.counts["production_dependencies"] == 1
    assert dataset.records["production_dependencies"] == {}
    assert {f.field for f in dataset.findings} == {"manufacturing_port_id", "output_product_id"}
    assert all(f.severity == "WARNING" and f.record_id == "D001" for f in dataset.findings)


def test_zip_with_wrapped_directory(data):
    archive = data / "data.zip"
    with ZipFile(archive, "w") as zip_file:
        for path in data.glob("*.csv"):
            zip_file.write(path, f"sample/{path.name}")
    assert load_dataset(archive).findings == []
