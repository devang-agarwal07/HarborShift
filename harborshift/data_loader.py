"""Read source datasets and validate their records and relationships."""

import csv
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal, InvalidOperation
from io import TextIOWrapper
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from . import models


TABLES = {
    "ports": models.Port,
    "routes": models.Route,
    "products": models.Product,
    "suppliers": models.Supplier,
    "shipments": models.Shipment,
    "shipment_legs": models.ShipmentLeg,
    "contracts": models.Contract,
    "production_dependencies": models.ProductionDependency,
    "disruptions": models.Disruption,
    "historical_delays_synthetic": models.HistoricalDelay,
}

EVENT_TYPES = {"congestion", "equipment_failure", "severe_weather", "strike"}
ENUM_VALUES = {
    "routes": {"status": {"open", "restricted", "closed"}},
    "products": {"category": {"raw_material", "finished_part"}},
    "suppliers": {"qualification_status": {"qualified", "unqualified", "pending"}},
    "shipments": {"status": {"planned", "in_transit", "delivered", "cancelled"}},
    "disruptions": {"event_type": EVENT_TYPES, "port_status": {"closed", "restricted"}},
    "historical_delays_synthetic": {
        "event_type": EVENT_TYPES | {"none"},
        "data_origin": {"synthetic"},
    },
}

REFERENCES = {
    "routes": {"from_port_id": "ports", "to_port_id": "ports"},
    "suppliers": {"port_id": "ports", "product_id": "products"},
    "shipments": {
        "product_id": "products", "origin_port_id": "ports",
        "destination_port_id": "ports", "contract_id": "contracts",
    },
    "shipment_legs": {"shipment_id": "shipments", "route_id": "routes"},
    "contracts": {"product_id": "products", "destination_port_id": "ports"},
    "production_dependencies": {
        "input_port_id": "ports", "input_product_id": "products",
        "manufacturing_port_id": "ports", "output_product_id": "products",
        "output_shipment_id": "shipments",
    },
    "disruptions": {"port_id": "ports"},
    "historical_delays_synthetic": {"port_id": "ports"},
}

OPTIONAL_TABLES = {"production_dependencies", "historical_delays_synthetic"}


@dataclass(frozen=True)
class Finding:
    filename: str
    row: int | None
    record_id: str
    field: str
    issue: str
    severity: str


class Dataset:
    def __init__(self):
        self.records = {table: {} for table in TABLES}
        self.counts = dict.fromkeys(TABLES, 0)
        self.findings: list[Finding] = []
        self._rows = {table: {} for table in TABLES}
        self._quarantined = {table: set() for table in OPTIONAL_TABLES}

    @property
    def is_valid(self):
        return all(finding.severity != "ERROR" for finding in self.findings)

    def require_valid(self):
        """Call before using the dataset for routing or simulation."""
        if not self.is_valid:
            raise ValueError("Dataset has blocking errors. Run the validation command.")

    def add_finding(self, table, key, field, issue, row=None):
        severity = "WARNING" if table in OPTIONAL_TABLES else "ERROR"
        if table in OPTIONAL_TABLES and key:
            self._quarantined[table].add(key)
        if row is None:
            row = self._rows[table].get(key)
        self.findings.append(Finding(f"{table}.csv", row, str(key), field, issue, severity))


def default_source(project_root):
    """Find the supplied dataset as a directory or the original ZIP."""
    for folder in ("data", "harber_shift_sample_datasets"):
        directory = project_root / folder
        for candidate in (directory, directory / "harber_shift_sample_datasets"):
            if any(candidate.glob("*.csv")):
                return candidate
        archive = directory / "harber_shift_sample_datasets.zip"
        if archive.is_file():
            return archive
    return project_root / "harber_shift_sample_datasets"


@contextmanager
def open_table(source, filename):
    if source.suffix.lower() == ".zip":
        with ZipFile(source) as archive:
            matches = [entry for entry in archive.infolist()
                       if PurePosixPath(entry.filename).name == filename]
            if not matches:
                raise FileNotFoundError(filename)
            if len(matches) > 1:
                raise ValueError(f"ZIP contains multiple entries named {filename}")
            with archive.open(matches[0]) as raw:
                with TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                    yield stream
    else:
        with (source / filename).open(encoding="utf-8-sig", newline="") as stream:
            yield stream


def parse_value(table, field, raw):
    if raw is None or not raw.strip():
        raise ValueError("value is required")
    raw = raw.strip()
    allowed = ENUM_VALUES.get(table, {}).get(field.name)
    if allowed is not None and raw not in allowed:
        raise ValueError(f"expected one of {', '.join(sorted(allowed))}; got {raw!r}")
    if field.type is date:
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            raise ValueError(f"expected a valid YYYY-MM-DD date; got {raw!r}") from None
        if value.isoformat() != raw:
            raise ValueError(f"expected YYYY-MM-DD; got {raw!r}")
        return value
    if field.type in (int, Decimal):
        try:
            value = field.type(raw)
        except (ValueError, InvalidOperation):
            raise ValueError(f"expected {field.type.__name__}; got {raw!r}") from None
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("expected a finite number")
        minimum = 1 if field.name == "leg_sequence" else 0
        if table == "disruptions" and field.name == "severity_1_to_5":
            minimum = 1
        if value < minimum:
            raise ValueError(f"must be at least {minimum}")
        if field.name in {"severity_1_to_5", "congestion_0_to_5"} and value > 5:
            raise ValueError("must be at most 5")
        return value
    return raw


def read_table(dataset, source, table, model):
    columns = fields(model)
    key_fields = ("shipment_id", "leg_sequence") if table == "shipment_legs" else (columns[0].name,)
    seen = set()
    try:
        with open_table(source, f"{table}.csv") as stream:
            reader = csv.DictReader(stream, strict=True)
            headers = reader.fieldnames or []
            missing = [field.name for field in columns if field.name not in headers]
            if missing or len(headers) != len(set(headers)):
                issue = f"missing columns: {', '.join(missing)}" if missing else "duplicate column names"
                dataset.add_finding(table, "", "header", issue, row=1)
                return
            for raw in reader:
                row = reader.line_num
                dataset.counts[table] += 1
                values = {}
                raw_id = "/".join((raw.get(name) or "").strip() for name in key_fields)
                valid = None not in raw
                if not valid:
                    dataset.add_finding(table, raw_id, "row", "more values than columns", row)
                for field in columns:
                    try:
                        values[field.name] = parse_value(table, field, raw.get(field.name))
                    except ValueError as error:
                        dataset.add_finding(table, raw_id, field.name, str(error), row)
                        valid = False
                if any(name not in values for name in key_fields):
                    continue
                parts = tuple(values[name] for name in key_fields)
                key = parts[0] if len(parts) == 1 else parts
                if key in seen:
                    dataset.add_finding(table, key, "/".join(key_fields), "duplicate ID", row)
                    continue
                seen.add(key)
                if valid:
                    dataset.records[table][key] = model(**values)
                    dataset._rows[table][key] = row
    except FileNotFoundError:
        dataset.add_finding(table, "", "file", "CSV missing")
    except (OSError, BadZipFile, ValueError, csv.Error) as error:
        dataset.add_finding(table, "", "file", str(error))
        dataset.records[table].clear()


def validate_references(dataset):
    for table, references in REFERENCES.items():
        for key, record in dataset.records[table].items():
            for field, target in references.items():
                value = getattr(record, field)
                if value not in dataset.records[target]:
                    dataset.add_finding(table, key, field, f"{value!r} has no matching record in {target}.csv")


def validate_shipments(dataset):
    records = dataset.records
    legs_by_shipment = {}
    for key, leg in records["shipment_legs"].items():
        legs_by_shipment.setdefault(leg.shipment_id, []).append(leg)
        if leg.planned_arrival_date < leg.planned_departure_date:
            dataset.add_finding("shipment_legs", key, "planned_arrival_date", "arrival is before departure")

    for key, shipment in records["shipments"].items():
        if shipment.planned_arrival_date < shipment.departure_date:
            dataset.add_finding("shipments", key, "planned_arrival_date", "arrival is before departure")
        contract = records["contracts"].get(shipment.contract_id)
        if contract:
            for field in ("product_id", "quantity_units", "destination_port_id"):
                expected = getattr(contract, field)
                if getattr(shipment, field) != expected:
                    dataset.add_finding("shipments", key, field, f"expected {expected} from contract {shipment.contract_id}")

        legs = sorted(legs_by_shipment.get(key, []), key=lambda leg: leg.leg_sequence)
        if [leg.leg_sequence for leg in legs] != list(range(1, len(legs) + 1)) or not legs:
            dataset.add_finding("shipments", key, "leg_sequence", "expected contiguous legs starting at 1")
        if not legs:
            continue

        previous_route = None
        previous_leg = None
        for leg in legs:
            route = records["routes"].get(leg.route_id)
            leg_key = (key, leg.leg_sequence)
            if previous_leg:
                if leg.planned_departure_date < previous_leg.planned_arrival_date:
                    dataset.add_finding("shipment_legs", leg_key, "planned_departure_date", "departure is before the previous leg arrives")
                if previous_route and route and previous_route.to_port_id != route.from_port_id:
                    dataset.add_finding("shipment_legs", leg_key, "route_id", f"route must start at previous destination {previous_route.to_port_id}")
            previous_leg, previous_route = leg, route

        first_route = records["routes"].get(legs[0].route_id)
        last_route = previous_route
        if first_route and first_route.from_port_id != shipment.origin_port_id:
            dataset.add_finding("shipments", key, "origin_port_id", f"first leg starts at {first_route.from_port_id}")
        if last_route and last_route.to_port_id != shipment.destination_port_id:
            dataset.add_finding("shipments", key, "destination_port_id", f"last leg ends at {last_route.to_port_id}")
        if shipment.departure_date != legs[0].planned_departure_date:
            dataset.add_finding("shipments", key, "departure_date", "does not match the first leg's planned departure")
        if shipment.planned_arrival_date != legs[-1].planned_arrival_date:
            dataset.add_finding("shipments", key, "planned_arrival_date", "does not match the last leg's planned arrival")


def validate_production(dataset):
    table = "production_dependencies"
    for key, dependency in dataset.records[table].items():
        shipment = dataset.records["shipments"].get(dependency.output_shipment_id)
        if shipment is None:
            continue
        if shipment.product_id != dependency.output_product_id:
            dataset.add_finding(table, key, "output_product_id", f"shipment {shipment.shipment_id} carries {shipment.product_id}, expected {dependency.output_product_id}")
        if shipment.origin_port_id != dependency.manufacturing_port_id:
            dataset.add_finding(table, key, "manufacturing_port_id", f"shipment {shipment.shipment_id} starts at {shipment.origin_port_id}, expected {dependency.manufacturing_port_id}")


def load_dataset(source: Path) -> Dataset:
    dataset = Dataset()
    for table, model in TABLES.items():
        read_table(dataset, source, table, model)
    validate_references(dataset)
    validate_shipments(dataset)
    validate_production(dataset)
    for table, keys in dataset._quarantined.items():
        for key in keys:
            dataset.records[table].pop(key, None)
    return dataset
