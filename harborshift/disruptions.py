"""Synthetic events and temporary transport network conditions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from .data_loader import EVENT_TYPES
from .graph import TransportGraph
from .models import Disruption


@dataclass(frozen=True)
class DisruptionEvent:
    event_id: str
    port_id: str
    event_type: str
    start: date
    duration_days: int
    severity: int
    port_status: str
    source: str = "manual simulation"
    confidence: str = "assumed"
    headline: str = ""

    def __post_init__(self):
        if not self.event_id.strip():
            raise ValueError("An event ID is required")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {self.event_type}")
        if self.port_status not in {"closed", "restricted"}:
            raise ValueError("Port status must be closed or restricted")
        if type(self.severity) is not int or not 1 <= self.severity <= 5:
            raise ValueError("Severity must be an integer from 1 to 5")
        if type(self.duration_days) is not int or self.duration_days < 0:
            raise ValueError("Duration must be a nonnegative number of whole days")
        try:
            self.end
        except OverflowError:
            raise ValueError("Disruption end is outside the supported date range") from None

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.duration_days)

    @classmethod
    def from_sample(cls, record: Disruption):
        return cls(
            event_id=record.event_id,
            port_id=record.port_id,
            event_type=record.event_type,
            start=record.reported_date,
            duration_days=record.expected_duration_days,
            severity=record.severity_1_to_5,
            port_status=record.port_status,
            source="synthetic CSV",
            headline=record.headline,
        )

    def restriction_days(self, on: date) -> int:
        """Estimate delay on an active restricted day, capped by reopening."""
        remaining = (self.end - on).days
        return min(remaining, (self.severity + 1) // 2)


@dataclass(frozen=True)
class RouteCondition:
    status: str
    estimated_delay_days: int
    event_ids: tuple[str, ...]


DelayEstimator = Callable[[DisruptionEvent, date, int], int]


class NetworkSnapshot:
    """Overlay events on the baseline graph for a scenario."""

    def __init__(self, graph: TransportGraph, events: tuple[DisruptionEvent, ...],
                 delay_estimator: DelayEstimator | None = None):
        self.graph = graph
        self.events = events
        self.delay_estimator = delay_estimator
        self._by_port: dict[str, list[DisruptionEvent]] = {}
        for event in events:
            self._by_port.setdefault(event.port_id, []).append(event)

    def events_at(self, port_id: str, on: date) -> tuple[DisruptionEvent, ...]:
        return tuple(event for event in self._by_port.get(port_id, ())
                     if event.start <= on < event.end)

    def restriction_wait(self, event: DisruptionEvent, on: date, transit_days: int) -> int:
        if self.delay_estimator is not None:
            return self.delay_estimator(event, on, transit_days)
        return event.restriction_days(on)

    def route_condition(self, route_id: str, on: date) -> RouteCondition:
        """Single-date status for a route. Itinerary checks date each endpoint separately."""
        route = self.graph.edge(route_id)
        ports = dict.fromkeys((route.from_port_id, route.to_port_id))
        events = tuple(event for port in ports for event in self.events_at(port, on))
        ids = tuple(event.event_id for event in events)
        if route.status == "closed" or any(event.port_status == "closed" for event in events):
            return RouteCondition("closed", 0, ids)
        if events:
            return RouteCondition("restricted", max(event.restriction_days(on) for event in events), ids)
        return RouteCondition(route.status, 0, ())
