"""Typed local API for HarborShift's shared scenario and routing services."""

from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from harborshift.data_loader import Dataset, default_source, load_dataset
from harborshift.disruptions import DisruptionEvent
from harborshift.graph import TransportGraph
from harborshift.news.fetch import AdvisoryCache, AdvisoryReport
from harborshift.models import Disruption, Port
from harborshift.routing import find_route
from harborshift.scenarios import run_scenario
from .schemas import RouteRecord, RouteResponse, ScenarioResponse, ShipmentRecord

ROOT = Path(__file__).resolve().parents[1]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
app = FastAPI(title="HarborShift", version="1.0.0")
advisories = AdvisoryCache()


@lru_cache(maxsize=1)
def get_dataset() -> Dataset:
    return load_dataset(default_source(ROOT))


def validated_dataset(dataset: Dataset = Depends(get_dataset)) -> Dataset:
    if not dataset.is_valid:
        issues = [finding for finding in dataset.findings if finding.severity == "ERROR"]
        raise HTTPException(503, detail=jsonable_encoder(issues))
    return dataset


Source = Annotated[Dataset, Depends(validated_dataset)]


class EventInput(BaseModel):
    port_id: str
    event_type: Literal["congestion", "equipment_failure", "severe_weather", "strike"]
    duration_days: NonnegativeInt
    severity: Annotated[int, Field(strict=True, ge=1, le=5)]
    port_status: Literal["closed", "restricted"]
    start: date | None = None
    advisory_replay: bool = False


class ScenarioInput(BaseModel):
    as_of: date
    sample_ids: list[str] = Field(default_factory=list, max_length=10)
    event: EventInput | None = None
    shipment_id: str | None = None
    manufacturing: bool = False
    units_per_container: PositiveInt | None = None
    use_ml: bool = False
    congestion: Annotated[int, Field(strict=True, ge=0, le=5)] = 0
    buffer_days: NonnegativeInt = 0
    original_purchase_inr: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None


class RouteInput(BaseModel):
    origin: str
    destination: str
    quantity_units: PositiveInt
    units_per_container: PositiveInt
    objective: Literal["fastest", "cheapest"] = "fastest"
    required_stops: list[str] = Field(default_factory=list, max_length=20)
    closed_ports: list[str] = Field(default_factory=list, max_length=20)
    closed_routes: list[str] = Field(default_factory=list, max_length=100)


def wire(value):
    return jsonable_encoder(value, custom_encoder={Decimal: float})


@app.get("/health")
def health(dataset: Source):
    return {"status": "ready", "data_origin": "synthetic", "shipment_count": len(dataset.records["shipments"])}


@app.get("/ports", response_model=list[Port])
def ports(dataset: Source):
    return wire(list(dataset.records["ports"].values()))


@app.get("/routes", response_model=list[RouteRecord])
def routes(dataset: Source):
    return wire(list(dataset.records["routes"].values()))


@app.get("/shipments", response_model=list[ShipmentRecord])
def shipments(dataset: Source):
    contracts = dataset.records["contracts"]
    return wire([{"shipment": shipment, "contract": contracts[shipment.contract_id]}
                 for shipment in dataset.records["shipments"].values()])


@app.get("/disruptions", response_model=list[Disruption])
def disruptions(dataset: Source):
    return wire(list(dataset.records["disruptions"].values()))


@app.post("/route", response_model=RouteResponse)
def route(query: RouteInput, dataset: Source):
    try:
        return wire(find_route(TransportGraph(dataset), **query.model_dump()))
    except (ValueError, OverflowError) as error:
        raise HTTPException(422, detail=str(error)) from error


@app.post("/simulate", response_model=ScenarioResponse)
def simulate(query: ScenarioInput, dataset: Source):
    try:
        events = ()
        if query.event:
            params = query.event.model_dump()
            params["start"] = params["start"] or query.as_of
            replay = params.pop("advisory_replay")
            source = "advisory replay with user assumptions" if replay else "manual simulation"
            events = (DisruptionEvent("manual", source=source, **params),)
        return wire(run_scenario(
            dataset, query.as_of, sample_ids=tuple(query.sample_ids), events=events,
            shipment_id=query.shipment_id, manufacturing=query.manufacturing,
            units_per_container=query.units_per_container, use_ml=query.use_ml,
            congestion=query.congestion, buffer_days=query.buffer_days,
            original_purchase_inr=query.original_purchase_inr,
        ))
    except (ValueError, OverflowError) as error:
        raise HTTPException(422, detail=str(error)) from error



@app.get("/news", response_model=AdvisoryReport)
def news(dataset: Source):
    return wire(advisories.get(list(dataset.records["ports"].values())))
