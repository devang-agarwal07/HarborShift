"""Isolated disruption scenarios built from one validated dataset."""

from datetime import date

from .data_loader import Dataset
from .disruptions import DelayEstimator, DisruptionEvent, NetworkSnapshot
from .graph import TransportGraph
from .impact import ItineraryIndex, SimulationResult, analyze


class Simulation:
    def __init__(self, dataset: Dataset):
        self.graph = TransportGraph(dataset)
        self._dataset = dataset
        self._itineraries = ItineraryIndex(dataset, self.graph)
        self._events: dict[str, DisruptionEvent] = {}

    def add_sample(self, event_id: str) -> bool:
        try:
            record = self._dataset.records["disruptions"][event_id]
        except KeyError:
            raise ValueError(f"Unknown sample event ID: {event_id}") from None
        return self.add_event(DisruptionEvent.from_sample(record))

    def add_event(self, event: DisruptionEvent) -> bool:
        try:
            self.graph.port(event.port_id)
        except KeyError:
            raise ValueError(f"Unknown port ID: {event.port_id}") from None
        previous = self._events.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise ValueError(f"Conflicting event ID: {event.event_id}")
            return False
        self._events[event.event_id] = event
        return True

    def reset(self) -> None:
        self._events.clear()

    def snapshot(self, delay_estimator: DelayEstimator | None = None) -> NetworkSnapshot:
        return NetworkSnapshot(self.graph, tuple(self._events.values()), delay_estimator)

    def run(
        self, as_of: date, snapshot: NetworkSnapshot | None = None, shipment_id: str | None = None,
    ) -> SimulationResult:
        return analyze(self._dataset, self._itineraries, snapshot or self.snapshot(), as_of, shipment_id)
