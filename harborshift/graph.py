"""Weighted, directed graph of the transport routes in a validated dataset."""

from dataclasses import dataclass

from .data_loader import Dataset
from .models import Port, Route


@dataclass(frozen=True)
class GraphSummary:
    port_count: int
    route_count: int


class TransportGraph:
    def __init__(self, dataset: Dataset):
        dataset.require_valid()
        self._ports: dict[str, Port] = dict(dataset.records["ports"])
        self._routes: dict[str, Route] = dict(dataset.records["routes"])

        outgoing: dict[str, list[Route]] = {port_id: [] for port_id in self._ports}
        for route in self._routes.values():
            outgoing[route.from_port_id].append(route)

        self._outgoing = {
            port_id: tuple(routes) for port_id, routes in outgoing.items()
        }

    @property
    def summary(self) -> GraphSummary:
        return GraphSummary(len(self._ports), len(self._routes))

    def port(self, port_id: str) -> Port:
        return self._ports[port_id]

    def edge(self, route_id: str) -> Route:
        return self._routes[route_id]

    @property
    def edges(self) -> tuple[Route, ...]:
        """Return all recorded edges in source order."""
        return tuple(self._routes.values())

    def neighbors(self, port_id: str) -> tuple[Route, ...]:
        """Return outgoing edges in source order, including parallel routes."""
        return self._outgoing[port_id]
