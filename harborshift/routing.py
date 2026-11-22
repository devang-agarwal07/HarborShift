"""Shortest paths for a conservative, fixed transport snapshot."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
from heapq import heappop, heappush
from itertools import pairwise
from typing import Literal

from .graph import TransportGraph
from .models import Route


Objective = Literal["fastest", "cheapest"]


@dataclass(frozen=True)
class ExcludedEdge:
    route_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RouteResult:
    required_containers: int
    excluded_edges: tuple[ExcludedEdge, ...]
    port_ids: tuple[str, ...] = ()
    route_ids: tuple[str, ...] = ()
    total_days: int | None = None
    freight_inr: Decimal | None = None
    no_route_reason: str | None = None

    @property
    def found(self) -> bool:
        return self.total_days is not None


def _exclude_edges(
    graph: TransportGraph,
    containers: int,
    closed_ports: Collection[str],
    closed_routes: Collection[str],
) -> dict[str, ExcludedEdge]:
    exclusions = {}
    for route in graph.edges:
        reasons = []
        if route.status == "closed":
            reasons.append("marked closed in route data")
        if route.route_id in closed_routes:
            reasons.append("closed in this snapshot")
        for port_id in (route.from_port_id, route.to_port_id):
            if port_id in closed_ports:
                reasons.append(f"port {port_id} is closed")
        if route.capacity_containers < containers:
            reasons.append(f"capacity {route.capacity_containers} below {containers} required")
        if reasons:
            exclusions[route.route_id] = ExcludedEdge(route.route_id, tuple(reasons))
    return exclusions


def _shortest_segment(
    graph: TransportGraph,
    start: str,
    end: str,
    objective: Objective,
    exclusions: dict[str, ExcludedEdge],
) -> list[Route] | None:
    best: dict[str, int | Decimal] = {start: 0}
    previous: dict[str, Route] = {}
    queue: list[tuple[int | Decimal, str]] = [(0, start)]

    while queue:
        weight, port_id = heappop(queue)
        if weight != best[port_id]:
            continue
        if port_id == end:
            path = []
            while port_id != start:
                edge = previous[port_id]
                path.append(edge)
                port_id = edge.from_port_id
            path.reverse()
            return path

        for edge in graph.neighbors(port_id):
            if edge.route_id in exclusions:
                continue
            edge_weight = edge.transit_days if objective == "fastest" else edge.cost_inr_per_container
            candidate = weight + edge_weight
            known = best.get(edge.to_port_id)
            if known is None or candidate < known:
                best[edge.to_port_id] = candidate
                previous[edge.to_port_id] = edge
                heappush(queue, (candidate, edge.to_port_id))

    return None


def find_route(
    graph: TransportGraph,
    origin: str,
    destination: str,
    *,
    quantity_units: int,
    units_per_container: int,
    objective: Objective = "fastest",
    required_stops: Sequence[str] = (),
    closed_ports: Collection[str] = (),
    closed_routes: Collection[str] = (),
) -> RouteResult:
    """Find a path through ordered stops, using CSV capacity as residual capacity."""
    for field, value in (
        ("quantity_units", quantity_units),
        ("units_per_container", units_per_container),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if objective not in ("fastest", "cheapest"):
        raise ValueError(f"Unknown routing objective: {objective}")

    stops = (origin, *required_stops, destination)
    closed_ports = frozenset(closed_ports)
    closed_routes = frozenset(closed_routes)
    for port_id in (*stops, *sorted(closed_ports)):
        try:
            graph.port(port_id)
        except KeyError:
            raise ValueError(f"Unknown port ID: {port_id}") from None
    for route_id in sorted(closed_routes):
        try:
            graph.edge(route_id)
        except KeyError:
            raise ValueError(f"Unknown route ID: {route_id}") from None

    containers = (quantity_units + units_per_container - 1) // units_per_container
    exclusions = _exclude_edges(graph, containers, closed_ports, closed_routes)
    excluded_edges = tuple(exclusions.values())
    for stop in stops:
        if stop in closed_ports:
            return RouteResult(containers, excluded_edges, no_route_reason=f"Required port {stop} is closed")

    # Each segment has the same load and fixed availability, so its weight is additive.
    path = []
    for start, end in pairwise(stops):
        segment = _shortest_segment(graph, start, end, objective, exclusions)
        if segment is None:
            return RouteResult(
                containers,
                excluded_edges,
                no_route_reason=f"No feasible path from {start} to {end}",
            )
        path.extend(segment)

    return RouteResult(
        required_containers=containers,
        excluded_edges=excluded_edges,
        port_ids=(origin, *(edge.to_port_id for edge in path)),
        route_ids=tuple(edge.route_id for edge in path),
        total_days=sum(edge.transit_days for edge in path),
        freight_inr=containers * sum(
            (edge.cost_inr_per_container for edge in path), Decimal(0)
        ),
    )
