"""Typed records for the supplied CSV tables."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Port:
    port_id: str
    port_name: str
    country: str


@dataclass(frozen=True)
class Route:
    route_id: str
    from_port_id: str
    to_port_id: str
    transit_days: int
    cost_inr_per_container: Decimal
    capacity_containers: int
    status: str


@dataclass(frozen=True)
class Product:
    product_id: str
    product_name: str
    category: str


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    supplier_name: str
    port_id: str
    product_id: str
    available_units: int
    lead_time_days: int
    unit_price_inr: Decimal
    qualification_status: str


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    product_id: str
    quantity_units: int
    origin_port_id: str
    destination_port_id: str
    departure_date: date
    planned_arrival_date: date
    contract_id: str
    status: str


@dataclass(frozen=True)
class ShipmentLeg:
    shipment_id: str
    leg_sequence: int
    route_id: str
    planned_departure_date: date
    planned_arrival_date: date


@dataclass(frozen=True)
class Contract:
    contract_id: str
    customer_name: str
    product_id: str
    quantity_units: int
    destination_port_id: str
    deadline: date
    late_penalty_inr_per_day: Decimal


@dataclass(frozen=True)
class ProductionDependency:
    dependency_id: str
    input_port_id: str
    input_product_id: str
    manufacturing_port_id: str
    output_product_id: str
    production_days: int
    output_shipment_id: str


@dataclass(frozen=True)
class Disruption:
    event_id: str
    reported_date: date
    port_id: str
    event_type: str
    expected_duration_days: int
    severity_1_to_5: int
    port_status: str
    headline: str


@dataclass(frozen=True)
class HistoricalDelay:
    record_id: str
    port_id: str
    event_type: str
    expected_duration_days: int
    severity_1_to_5: int
    congestion_0_to_5: int
    planned_transit_days: int
    schedule_buffer_days: int
    actual_delay_days: Decimal
    data_origin: str
