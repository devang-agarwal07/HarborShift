"""HTTP response shapes with JSON numbers for monetary amounts."""

from dataclasses import dataclass

from harborshift.impact import ShipmentImpact
from harborshift.models import Contract, Route, Shipment
from harborshift.recovery import RecoveryOption, RecoveryResult
from harborshift.routing import RouteResult
from harborshift.scenarios import ScenarioReport


@dataclass(frozen=True)
class RouteRecord(Route):
    cost_inr_per_container: float


@dataclass(frozen=True)
class ContractRecord(Contract):
    late_penalty_inr_per_day: float


@dataclass(frozen=True)
class ShipmentRecord:
    shipment: Shipment
    contract: ContractRecord


@dataclass(frozen=True)
class RouteResponse(RouteResult):
    freight_inr: float | None = None


@dataclass(frozen=True)
class ImpactRecord(ShipmentImpact):
    penalty_per_day: float


@dataclass(frozen=True)
class RecoveryOptionRecord(RecoveryOption):
    freight_inr: float | None = None
    purchase_inr: float | None = None
    penalty_inr: float | None = None
    total_future_inr: float | None = None


@dataclass(frozen=True)
class RecoveryRecord(RecoveryResult):
    options: tuple[RecoveryOptionRecord, ...]


@dataclass(frozen=True)
class ScenarioResponse(ScenarioReport):
    impacts: tuple[ImpactRecord, ...]
    estimated_penalties_inr: float
    recovery: tuple[RecoveryRecord, ...]
