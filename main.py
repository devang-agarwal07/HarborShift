"""HarborShift command-line entry point."""

import argparse
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from harborshift.data_loader import Dataset, EVENT_TYPES, default_source, load_dataset
from harborshift.disruptions import DisruptionEvent
from harborshift.graph import TransportGraph
from harborshift.routing import RouteResult, find_route
from harborshift.scenarios import run_scenario


def print_validation(dataset: Dataset, source: Path) -> int:
    print(f"Dataset: {source}")
    print("CSV records (read / retained):")
    for table, count in dataset.counts.items():
        print(f"  {table}.csv: {count} / {len(dataset.records[table])}")
    for finding in dataset.findings:
        row = f" row {finding.row}" if finding.row is not None else ""
        record = f" [{finding.record_id}]" if finding.record_id else ""
        print(f"{finding.severity}: {finding.filename}{row}{record} "
              f"{finding.field}: {finding.issue}")

    errors = sum(finding.severity == "ERROR" for finding in dataset.findings)
    warnings = len(dataset.findings) - errors
    print(f"Validation {'passed' if dataset.is_valid else 'failed'} "
          f"({errors} errors, {warnings} warnings).")
    return 0 if dataset.is_valid else 1


def print_neighbors(graph: TransportGraph, port_id: str) -> int:
    try:
        port = graph.port(port_id)
    except KeyError:
        print(f"Unknown port ID: {port_id}", file=sys.stderr)
        return 1

    summary = graph.summary
    print(f"Graph: {summary.port_count} ports, {summary.route_count} routes")
    print(f"Outgoing routes from {port.port_name} ({port.port_id}):")
    routes = graph.neighbors(port_id)
    if not routes:
        print("  No outgoing routes.")
    for route in routes:
        destination = graph.port(route.to_port_id)
        print(f"  {route.route_id} -> {destination.port_name} ({destination.port_id}): "
              f"{route.transit_days} days, {route.cost_inr_per_container} INR/container, "
              f"capacity {route.capacity_containers} containers, {route.status}")
    return 0


def print_route_result(label: str, graph: TransportGraph, result: RouteResult) -> None:
    print(label)
    if result.found:
        ports = " -> ".join(
            f"{graph.port(port_id).port_name} ({port_id})" for port_id in result.port_ids
        )
        print(f"  Ports: {ports}")
        print(f"  Route IDs: {', '.join(result.route_ids) or 'none (same port)'}")
        print(f"  Transit: {result.total_days} days")
        print(f"  Estimated freight: {result.freight_inr:,.2f} INR")
    else:
        print(f"  No route. {result.no_route_reason}.")
    if result.excluded_edges:
        print(f"  Excluded routes ({len(result.excluded_edges)}):")
        for edge in result.excluded_edges:
            print(f"    {edge.route_id}: {', '.join(edge.reasons)}")


def run_route_command(graph: TransportGraph, args: argparse.Namespace) -> int:
    options = {
        "quantity_units": args.quantity,
        "units_per_container": args.units_per_container,
        "objective": args.objective,
        "required_stops": args.via,
    }
    try:
        snapshot = find_route(
            graph, args.origin, args.destination,
            closed_ports=args.close_port, closed_routes=args.close_route, **options,
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Objective: {args.objective}")
    print(f"Packing assumption: {args.quantity} units at {args.units_per_container} "
          f"units/container requires {snapshot.required_containers} container(s)")
    if args.via:
        print(f"Required stops in order: {' -> '.join(args.via)}")
    if args.close_port or args.close_route:
        baseline = find_route(graph, args.origin, args.destination, **options)
        print_route_result("Baseline", graph, baseline)
        print_route_result(
            "Conservative static scenario (closures apply for the full planning horizon)",
            graph, snapshot,
        )
    else:
        print_route_result("Baseline", graph, snapshot)
    return 0


def simulation_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("use a valid date in YYYY-MM-DD format")


def run_simulation_command(dataset: Dataset, args: argparse.Namespace) -> int:
    manual = (args.port, args.event_type, args.duration, args.severity, args.status)
    if any(value is not None for value in (*manual, args.start)):
        if any(value is None for value in manual):
            print("A manual event requires --port, --event-type, --duration, --severity, and --status.",
                  file=sys.stderr)
            return 1
    try:
        events = ()
        if args.port is not None:
            events = (DisruptionEvent(
                "manual", args.port, args.event_type, args.start or args.as_of,
                args.duration, args.severity, args.status,
            ),)
        result = run_scenario(
            dataset, args.as_of, sample_ids=tuple(args.event), events=events,
            shipment_id=args.shipment, manufacturing=args.manufacturing,
            units_per_container=args.units_per_container, use_ml=args.use_ml,
            congestion=args.congestion, buffer_days=args.buffer_days,
            original_purchase_inr=Decimal(args.original_purchase_inr) if args.original_purchase_inr else None,
        )
    except (ValueError, OverflowError, InvalidOperation) as error:
        print(f"Simulation input error: {error}", file=sys.stderr)
        return 1

    print(f"Synthetic simulation as of {result.as_of}")
    for event in result.events:
        print(f"Event {event.event_id}: {event.port_id} {event.port_status} ({event.event_type}, "
              f"severity {event.severity}) from {event.start} to {event.end} (end excluded, {event.source})")
    if not result.impacts:
        print("No matching shipment port calls.")
    for impact in result.impacts:
        print(f"{impact.shipment_id} ({impact.contract_id}): ETA {impact.baseline_eta} -> "
              f"{impact.revised_eta}, deadline {impact.deadline}, slack {impact.slack_days} day(s)")
        for call in impact.calls:
            print(f"  {call.status}: {call.port_id} {call.call_type} on {call.call_date}, "
                  f"leg {call.leg_sequence} ({call.route_id}), "
                  f"event(s) {', '.join(call.event_ids)}, wait {call.wait_days} day(s)")
    print("Urgent contracts (smallest slack, then highest daily penalty):")
    if not result.urgent_contract_ids:
        print("  None.")
    for contract_id in result.urgent_contract_ids:
        if result.manufacturing:
            delivery = result.cascade[-1]
            days = max(0, (delivery.revised.finish - result.customer_deadline).days)
            print(f"  {contract_id}: ETA {delivery.revised.finish}, {days} late day(s), "
                  f"estimated penalty {result.estimated_penalties_inr:,.2f} INR")
        else:
            impact = min((item for item in result.impacts if item.contract_id == contract_id
                          and any(call.wait_days for call in item.calls)),
                         key=lambda item: (item.slack_days, item.shipment_id))
            print(f"  {contract_id} via {impact.shipment_id}: ETA {impact.revised_eta}, "
                  f"{impact.late_days} late day(s), estimated penalty {impact.estimated_penalty:,.2f} INR")
    if result.cascade:
        print("Manufacturing delivery chain:")
        for task in result.cascade:
            print(f"  {task.label}: {task.baseline.finish} -> {task.revised.finish}")
            if task.direct_delay_days:
                print(f"    Direct port wait: {task.direct_delay_days} day(s)")
            if task.reason_paths:
                print("    Dependency path: " + ", ".join(" -> ".join(path) for path in task.reason_paths))
    if args.recover or args.manufacturing:
        if not result.recovery:
            print("No directly affected shipment requires recovery options.")
        for recovery in result.recovery:
            print(f"Recovery for {recovery.contract_id} via {recovery.shipment_id}:")
            print(f"  Recommended: {recovery.recommended_id or 'no feasible option'}")
            if recovery.recommended_id and not recovery.deadline_feasible:
                print("  No option meets the deadline.")
            for option in recovery.options:
                cost = f"{option.total_future_inr:,.2f} INR" if option.total_future_inr is not None else "unknown"
                timing = f"ETA {option.eta}, freight {option.freight_inr:,.2f} INR, penalty {option.penalty_inr:,.2f} INR, future cost {cost}. " if option.eta else ""
                print(f"  {option.option_id} ({option.kind}, {option.status}): {timing}{option.reason}")
            for warning in recovery.warnings:
                print(f"  Note: {warning}")
    if args.use_ml:
        print("Delay source: " + ", ".join(result.prediction.sources))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="HarborShift dataset and network tools")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="check source CSVs and report findings")
    neighbors = commands.add_parser("neighbors", help="list directed routes leaving a port")
    neighbors.add_argument("port_id", help="origin port ID, such as P01")
    route = commands.add_parser("route", help="find a fastest or cheapest path and compare closures")
    route.add_argument("origin", help="origin port ID")
    route.add_argument("destination", help="destination port ID")
    route.add_argument("--quantity", type=int, required=True, help="shipment quantity in units")
    route.add_argument("--units-per-container", type=int, required=True, help="assumed units per container")
    route.add_argument("--objective", choices=("fastest", "cheapest"), default="fastest")
    route.add_argument("--via", action="append", default=[], metavar="PORT", help="required stop, repeat in order")
    route.add_argument("--close-port", action="append", default=[], metavar="PORT", help="port closed for the scenario")
    route.add_argument("--close-route", action="append", default=[], metavar="ROUTE", help="route closed for the scenario")
    simulate = commands.add_parser("simulate", help="evaluate direct impacts of a synthetic port event")
    simulate.add_argument("--as-of", type=simulation_date, required=True, help="simulation date")
    simulate.add_argument("--event", action="append", default=[], metavar="ID", help="sample event, repeatable")
    simulate.add_argument("--port", help="port ID for a manual event")
    simulate.add_argument("--event-type", choices=sorted(EVENT_TYPES))
    simulate.add_argument("--duration", type=int, help="manual event duration in calendar days")
    simulate.add_argument("--severity", type=int, help="manual event severity from 1 to 5")
    simulate.add_argument("--status", choices=("closed", "restricted"))
    simulate.add_argument("--start", type=simulation_date, help="manual start date (defaults to --as-of)")
    simulate.add_argument("--manufacturing", action="store_true", help="use the derived manufacturing demo")
    simulate.add_argument("--recover", action="store_true", help="show ranked recovery options")
    simulate.add_argument("--shipment", help="evaluate one original shipment ID")
    simulate.add_argument("--units-per-container", type=int, help="synthetic packing assumption")
    simulate.add_argument("--original-purchase-inr", help="explicit purchase cost assumption")
    simulate.add_argument("--use-ml", action="store_true", help="predict delay for restricted calls")
    simulate.add_argument("--congestion", type=int, default=0, help="assumed ML congestion (0 to 5)")
    simulate.add_argument("--buffer-days", type=int, default=0, help="assumed ML schedule buffer")
    for command in (validate, neighbors, route, simulate):
        command.add_argument("--data", type=Path, help="path to the CSV directory or dataset ZIP")

    args = parser.parse_args(argv)
    source = args.data or default_source(Path(__file__).resolve().parent)
    dataset = load_dataset(source)

    if args.command == "validate" or not dataset.is_valid:
        return print_validation(dataset, source)
    if args.command == "simulate":
        return run_simulation_command(dataset, args)
    graph = TransportGraph(dataset)
    if args.command == "neighbors":
        return print_neighbors(graph, args.port_id)
    return run_route_command(graph, args)


if __name__ == "__main__":
    raise SystemExit(main())
