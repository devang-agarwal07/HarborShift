# HarborShift — implementation plan for Codex

## 1. Project objective

Build a working web-based supply-chain disruption simulator and decision-support tool. A company in India relies on overseas raw-material suppliers, a manufacturing facility in South Africa, and delivery to Indian customers. HarborShift should detect or simulate a disruption, find the shipments and contracts affected, estimate delay, and compare feasible recovery options (reroute, wait, or source from an alternative qualified supplier).

The DSA engine is the project core. Machine learning predicts delay; it does not choose the recovery action. The user ultimately decides whether to act. This is a student prototype, not an actual shipping-control or procurement system.

## 2. Instructions to Codex

- Inspect the existing project tree, dataset README and CSV headers before modifying anything. Preserve existing files and naming conventions. Locate the supplied dataset folder whether it is named `harber_shift_sample_datasets` or placed under `data/`.
- Follow the milestones in order. Start with Milestone 1 ONLY. At the end of each milestone, run the stated tests, update the progress checklist and README, explain what was implemented, report issues, and stop for the student's approval before implementing the next milestone.
- Write readable, modular, beginner-friendly code. Implement adjacency lists, graph traversal, Dijkstra, deadline prioritization and supplier selection explicitly; do not delegate core DSA to a graph library.
- Use the checked-in CSV files as source data. Never silently overwrite, invent or "fix" original records. Report inconsistent records and create clearly marked derived fixtures when needed.
- Make the simulation fully runnable offline. Live news and ML are additions, not prerequisites for demonstrating the DSA.
- Do not embed secrets, use paid services, automate purchases or claim that fictional data represents real-world conditions. Keep actual and simulated dates, events and metrics clearly separate.
- Add automated tests as each component is built. Avoid premature complexity, extensive frameworks, and large rewrites.

## 3. Technology choices

| Layer | Technology |
|---|---|
| Core algorithms | Python 3, standard library, dataclasses, dictionaries, heapq |
| Reading CSVs | csv, pathlib, datetime |
| Backend | FastAPI and Pydantic (after DSA works) |
| ML | pandas, scikit-learn, joblib |
| News | RSS or documented public advisories, feedparser and HTTP requests |
| UI | React + Vite; simple CSS; a schematic network graph initially |
| Tests | pytest |
| Storage | Original CSVs; no database needed for MVP |

A single Python backend keeps the solo project manageable. Confirm with faculty if core algorithms must be implemented in C++ or Java before introducing a second language. If so, clarify the integration contract before coding. Do not add React/FastAPI/ML dependencies in Milestone 1 unless already present.

## 4. Target folder structure

```text
harber_shift/
├── HARBORSHIFT_IMPLEMENTATION_PLAN.md
├── data/                         # existing 10 CSVs + dataset README (or existing folder)
│   └── fixtures/                 # clearly labelled, derived/test-only data
├── harborshift/
│   ├── __init__.py
│   ├── models.py
│   ├── data_loader.py
│   ├── graph.py
│   ├── routing.py
│   ├── disruptions.py
│   ├── impact.py
│   ├── recovery.py
│   ├── simulation.py
│   ├── ml/
│   │   ├── train.py
│   │   └── predict.py
│   └── news/
│       ├── fetch.py
│       └── extract.py
├── api/
│   └── main.py
├── frontend/
├── tests/
├── artifacts/                    # trained model + evaluation report
├── main.py                       # initial CLI demo
├── requirements.txt
├── .gitignore
└── README.md
```

Create modules only as their milestones require them. Use relative paths resolved from the project directory rather than hard-coded Windows paths.

## 5. Existing dataset contract

Verify these expected headers against the actual files before coding.

| File | Rows | Essential columns and role |
|---|---:|---|
| ports.csv | 20 | port_id, port_name, country; graph nodes |
| routes.csv | 50 | route_id, from_port_id, to_port_id, transit_days, cost_inr_per_container, capacity_containers, status; directed edges |
| products.csv | 5 | product_id, product_name, category |
| suppliers.csv | 30 | supplier_id, supplier_name, port_id, product_id, available_units, lead_time_days, unit_price_inr, qualification_status |
| shipments.csv | 100 | shipment_id, product_id, quantity_units, origin_port_id, destination_port_id, departure_date, planned_arrival_date, contract_id, status |
| shipment_legs.csv | 232 | shipment_id, leg_sequence, route_id, planned_departure_date, planned_arrival_date |
| contracts.csv | 100 | contract_id, customer_name, product_id, quantity_units, destination_port_id, deadline, late_penalty_inr_per_day |
| production_dependencies.csv | 2 | dependency_id, input_port_id, input_product_id, manufacturing_port_id, output_product_id, production_days, output_shipment_id |
| disruptions.csv | 5 | event_id, reported_date, port_id, event_type, expected_duration_days, severity_1_to_5, port_status, headline |
| historical_delays_synthetic.csv | 2,000 | record_id, port_id, event_type, expected_duration_days, severity_1_to_5, congestion_0_to_5, planned_transit_days, schedule_buffer_days, actual_delay_days, data_origin |

All data is synthetic. Dates refer to a fictional January 2027 scenario. Ports are real names but shipping services, times, events, suppliers and costs are assumed. Port coordinates are not present: use a schematic network or add verified coordinates in a separate file later. Do not present straight-line schematic edges as actual navigable sea routes.

### Important data limitations

- The production dependency file is only illustrative. In the original sample, D001 names PR03 while SH001 carries PR04. Report this and any other product/port mismatch; never propagate such an invalid dependency as though it were verified. Create a separate coherent manufacturing demo fixture: raw material shipment to factory, production task, finished-part shipment from factory, final contract. Link these explicitly by task IDs and product IDs. Include production duration and planned schedule.
- Original shipments describe a single product across ordered legs; passing through a port does not automatically manufacture a new product. A route from the USA to India must not bypass a required South African manufacturing task.
- Shipment quantity is units; route capacity is containers. Add a configurable, explicitly synthetic units-per-container assumption for each demo product before comparing capacity or computing transport cost. Use ceiling division. Treat route capacity as illustrative residual availability for a single decision initially; shared allocation is an extension.
- Congestion and schedule-buffer inputs are not supplied by the disruption file. Accept explicit demo assumptions or validated inputs; never claim they came from a real source.
- Supplier unit price and freight cost have different units; convert to total INR before comparison. Distinguish estimated total future cost from true incremental cost: purchase commitments and cancellation fees are absent.

## 6. Core domain logic

- Transport graph G: directed nodes = ports, edges = available transport services. Edge attributes = time, cost, capacity and status.
- Dependency DAG: separate graph of tasks/shipments/manufacturing/contract delivery. An edge means the successor cannot start until its predecessor is ready.
- Event: port, event type, start date (reported_date used as an explicit demo approximation), duration, severity, status, source and confidence. Use half-open date intervals [start, end).
- Shipment itinerary: ordered legs keyed by shipment_id. Evaluate actual itinerary and schedule, not only origin and destination.
- Simulation state: as_of date, injected event(s), assumptions, planned itinerary, derived disruption status. Original graph and CSV inputs remain unchanged when comparing scenarios.
- A planned shipment may be rerouted before departure; for an in-transit shipment reroute only from the next reachable decision point. If the shipment's location/progress is unknown, mark the reroute as conditional rather than asserting that it can be changed mid-ocean.

### Important calculations

- Baseline path duration = sum of edge transit days.
- Required containers = ceil(quantity units / assumed units per container).
- Transport cost = sum of per-container edge costs × required containers.
- Revised ETA = planned/recomputed arrival + applicable estimated delay (avoid double-counting a closure already included in routing).
- Late days = max(0, revised delivery date − contract deadline); convert any fractional delay to a documented conservative calendar-day convention.
- Penalty estimate = late days × contract's daily penalty.
- Deadline slack = deadline − ETA.
- Supplier ETA = decision date + lead time + feasible transit time + explicit handling assumption, if used. For a qualified supplier at destination, transit time can be zero in the demo.
- Estimated sourcing option cost = quantity × unit price + freight + estimated penalty; label unknown existing commitments and fees separately.

## 7. Ordered implementation milestones

### Milestone 1 — Repository setup and data validation

1. Inspect existing folder and actual CSV headers.
2. Create minimal Python package, CLI entrypoint, README, requirements and tests.
3. Build typed models and CSV loaders. Parse numeric fields and ISO dates; index records by primary ID.
4. Validate uniqueness, foreign keys, nonnegative costs/durations/capacities, valid enum values, chronological dates, contiguous shipment leg sequences, route continuity, planned route origins/destinations, matching contract quantities/products and production dependency consistency.
5. Produce a data summary and validation report with filename, row/ID, field, issue and severity. Fatal transport-data errors must prevent dependent operations; invalid optional production rows can be quarantined with a visible warning.

**Acceptance:** `python main.py validate` prints dataset counts and actionable validation findings; tests cover a missing CSV, duplicate ID, broken foreign key, invalid date, invalid dependency, and a valid fixture. Do not start ML, backend or frontend.

### Milestone 2 — Weighted directed graph

1. Build adjacency lists mapping port_id to edge objects.
2. Preserve isolated vertices, parallel routes and direction; do not add reverse edges unless they exist in CSV.
3. Load all transport routes. Expose neighbors, edge lookup and a read-only graph summary.

**Acceptance:** all 20 expected vertices and 50 edges load when the original files are valid; test directionality, isolation and parallel edges. CLI lists neighbors of P01, with names, days and cost.

**DSA:** adjacency list O(V+E) storage, hash maps for indexed lookups.

### Milestone 3 — Routing

1. Implement Dijkstra using a min-heap; ignore stale heap entries.
2. Reconstruct exact port IDs AND route IDs using predecessor edges. Return no-route status safely when unreachable.
3. Support fixed snapshots: fastest and cheapest objectives independently. Filter closed ports/routes and insufficient residual capacity with supplied packing assumptions. Preserve the same start/end and required manufacturing stops.
4. For the first MVP, route around closures assumed unavailable for the candidate planning horizon. A route that becomes available later can be compared via the wait option. Label this as a conservative static scenario; fully time-dependent routing is optional.
5. Return total time, estimated freight, and an explanation for excluded edges. Do not assert that the fastest route is always the cheapest route meeting a deadline. If you later explore multiple feasible alternatives, implement a bounded k-path or label-setting method and report its limits.

**Acceptance:** CLI compares a baseline path with a path after closing P05 (Durban) on a suitable fixture; tests verify the true shortest path, unreachable destination, start=destination, direction, closed port and capacity. Dijkstra time O((V+E) log V) for a simple graph with a binary heap; lazy heaps/parallel edges can use O((V+E) log E), space O(V+E).

### Milestone 4 — Disruption simulation and direct impact

1. Create event objects from disruptions.csv and allow manually choosing simulated port, event type, duration, severity and as_of date.
2. Maintain temporary graph state, marking closures or adding explicit delay to restricted routes. Do not mutate baseline data.
3. Index shipment legs by port and route. Check event interval versus relevant scheduled departure/arrival or port call (use a documented demo dwell convention); avoid treating a ship at sea as present at both ports for its entire transit.
4. Separate confirmed modeled impact, possible future exposure and already-completed legs. Recompute ETA with a transparent wait estimate. Compare it with contract deadline.
5. Use a heap to sort at-risk contracts by chosen deterministic urgency rule, such as smallest slack then highest penalty.

**Acceptance:** injected disruption affects only relevant shipments in the modeled time window; tests cover unaffected shipment, boundary dates, closed origin/destination, duplicate event, and safe reset. CLI prints affected shipment IDs, ETA and urgent contracts.

### Milestone 5 — Cascading manufacturing impact

1. Build an explicit, small valid manufacturing fixture from separate input and output shipments. Document any derived values and why the original dependency file is incomplete.
2. Traverse task dependencies with BFS/DFS to identify impacted descendants. Use Kahn's topological sort for schedule recomputation and detect cycles.
3. Calculate each task's earliest start as the maximum of planned start and predecessor finish times, then add task duration. Downstream tasks can absorb delays with slack. For multiple predecessor inputs, wait for all required material.
4. Report direct versus downstream impact and the reason path explaining each dependency.

**Acceptance:** demonstrate USA raw-material shipment → South African production → India finished-part shipment → customer. Delay raw material by several days and show revised production/contract ETA; test chain, branching, converging dependencies, schedule slack and cycle rejection.

### Milestone 6 — Recovery recommendation engine

1. Generate candidate options: continue/wait, feasible alternate transportation, alternative qualified supplier with compatible product and enough quantity.
2. Evaluate each option's lead time, delivery ETA, freight, capacity, deadline, and estimated penalty. Respect manufacturing constraints and the physically reachable decision point.
3. Rank deadline-feasible options by estimated future cost and then ETA. If none meets the deadline, report that plainly and rank late options using penalty and cost, with the ranking policy shown. Compare only costs on a consistent basis; if original purchase cost or cancellation fee is unknown, flag that limitation.
4. Return alternatives with reasons for accepted/rejected candidates; use a deterministic sorted list or heap. Single-supplier, full-quantity selection is the MVP. Multi-supplier split, shared capacity, and min-cost flow are optional future work.

**Acceptance:** end-to-end CLI demonstrates disruption → affected contracts → options → recommendation. Tests include wrong product, insufficient stock, unqualified source, impossible route, local supplier, no feasible option, and choosing a cheaper on-time alternative over an expensive faster one.

**MVP checkpoint:** A working offline simulator exists before any ML.

### Milestone 7 — ML delay prediction

1. Inspect historical_delays_synthetic.csv. Target = actual_delay_days. Exclude record_id, data_origin and target from features. Use only fields known at prediction time.
2. Build one scikit-learn Pipeline with categorical one-hot encoding (handle unseen categories) and numeric preprocessing. Use fixed-seed train/validation/test separation, fitting preprocessing only on training data. Compare mean/median baseline, linear regression, random forest and gradient boosting.
3. Record held-out MAE and RMSE in days, and compare with the simple baseline. Select model based on validation MAE; use test once after selection. Save the fitted pipeline with feature schema and evaluation report.
4. Create predict_delay() returning nonnegative predicted days, model version, and source (synthetic_model or rule_fallback). Validate required inputs and reject bad ranges. Report demo assumptions for missing congestion/buffer.
5. Use ML delay estimates in impact analysis, avoiding adding the same disruption twice. Preserve the fallback rule-based estimator so the demo works without the model. Do not claim real-world predictive performance from synthetic labels.
6. Research verified historical data later. A real model requires planned and actual arrival dates and corresponding disruption features observed before the arrival outcome. Evaluate chronologically when using real dated records.

**Acceptance:** `python -m harborshift.ml.train` creates a reproducible report and model; test prediction on valid data, unseen event category policy, missing inputs and absent model. Show actual held-out values (not invented accuracy numbers).

### Milestone 8 — Backend API

Expose typed endpoints with shared core services rather than reimplementing DSA in web handlers:

| Endpoint | Purpose |
|---|---|
| GET /health | Check backend readiness |
| GET /ports | Port list |
| GET /routes | Graph edges |
| GET /shipments | Shipments and contract summaries |
| GET /disruptions | Sample events |
| POST /route | Baseline or disrupted route query |
| POST /simulate | One complete scenario: impact, ETA, recovery options |

`POST /simulate` accepts as_of, shipment selection or all, disruption parameters, and packing/ML assumptions. Its result includes scenario ID, event, affected port/edge IDs, affected shipment IDs, baseline ETA, revised ETA, late days, prediction source, ranked options, estimated costs, feasibility and warnings. Use JSON ISO dates and numeric amounts with explicit units. Keep simulations isolated; restart/reset should return to the baseline.

**Acceptance:** API tests exercise valid scenario, invalid port/data, impossible route, and repeated isolated scenarios. Document local start command and example requests.

### Milestone 9 — Interactive dashboard

Build a local React interface using the API:

- Navigation: overview, network & simulator, shipments/contracts, disruptions, and recovery.
- KPI cards: total shipments, modeled affected shipments, contracts at risk, and estimated penalties.
- Interactive network: labelled port nodes and directed edges; affected routes red, available routes neutral, selected recovery route green or distinct patterned lines. Show legend and route time/cost. Keep coordinates schematic unless independently verified.
- Scenario controls: simulated date, port, event severity/type/duration, choose sample event, apply and reset.
- Timeline: planned ETA, revised ETA, contract deadline and selected recovery ETA. Show manufacturing cascade where relevant.
- Options table: original plan, alternate route, supplier; date, cost, penalty, feasibility, reason.
- Show loading, empty, error, no-route and no-feasible-option states. Label sample data and synthetic ML prominently. No misleading claims about live ship positions.

**Acceptance:** use the real backend, not hard-coded result cards. One click on a simulated event changes affected items and alternatives; reset restores baseline. Test at desktop and smaller viewport sizes. Keep interface accessible and readable without color alone.

### Milestone 10 — Live public disruption monitoring

Only add after the offline system and dashboard work.

1. Configure public RSS feeds and official advisories; use documented interfaces, respect source terms/rate limits, use timeouts and handle failed feeds.
2. Store article title, URL, timestamp, source and normalized event candidates. Deduplicate by normalized URL or content hash.
3. Extract event type and explicit port/location matches using keywords and a port-alias dictionary. Treat ambiguous locations, unknown duration and unknown severity as unknown; avoid fabricating facts. Optionally improve NLP later.
4. Display source, extracted facts, confidence/verification status and timestamp. Let the user review uncertain events before injecting them.
5. Apply live events only to genuinely dated matching shipments. Historical sample scenario dates cannot be silently matched to today's articles; provide a separately labelled replay or a user-selected simulated date if demonstrating a news event with sample data.

**Acceptance:** use offline RSS fixtures to test parsing, deduplication, irrelevant article, ambiguous place, missing duration and network failure. The offline simulator still works when no feed responds.

### Milestone 11 — End-to-end QA and college demonstration

- Test the full offline chain: original plan → port disruption → cascading delay → at-risk contract → recommendation → reset.
- Test alternate supplier recovery, route recovery, no recovery feasible, no affected shipments, simultaneous impacts and missing ML/news availability. Document unsupported cases.
- Record algorithm complexity, dataset assumptions, ML metrics, screenshots/diagrams, setup/run commands and sample scenarios.
- Prepare a 3–5 minute walkthrough: choose contract, inject disruption, watch graph/timeline change, inspect recommendation, explain graph/Dijkstra/BFS/DAG/heap, switch between rule estimate and ML forecast.
- Report what is implemented, what is simulated, limitations and measurable outcomes. Do not describe the prototype as production-grade or automatically able to purchase capacity.

**Acceptance:** clean checkout can be launched using README instructions; tests pass; demo works without paid APIs or internet.

## 8. Suggested solo schedule

| Week | Milestones | Outcome |
|---|---|---|
| 1 | 1–3 | Validated datasets, graph and CLI routing |
| 2 | 4–6 | Offline disruption and recovery MVP |
| 3 | 7–8 | ML experiment and API integration |
| 4 | 9 | Interactive website |
| 5 | 10–11 | Optional news monitoring, tests, documentation |
| 6 | Buffer | Fixes, presentation, optional enhancements |

If behind schedule, prioritize Milestones 1–6, 8–9 and testing, and defer live feeds or advanced ML. Do not compromise algorithm correctness to finish a larger feature list.

## 9. Progress checklist

- [x] Project concept and sample CSV dataset creation
- [x] M1: repository setup and data validation
- [x] M2: directed graph
- [x] M3: Dijkstra and route comparison
- [x] M4: disruption simulation and direct impact
- [x] M5: dependency DAG and cascading delay
- [x] M6: supplier and route recommendation (offline MVP)
- [x] M7: delay regression model and evaluation
- [x] M8: backend API
- [x] M9: interactive frontend
- [x] M10: live news ingestion
- [x] M11: end-to-end testing and presentation

## 10. First command to give Codex

Read HARBORSHIFT_IMPLEMENTATION_PLAN.md and inspect the existing project and supplied sample dataset folder. Implement Milestone 1 only: setup, typed CSV loading, validation, tests and README. Preserve the original datasets. Run tests, report all validation issues (including any production dependency inconsistency), explain the folder structure and how I run the program on Windows, and stop before Milestone 2. I am a second-year CSE student; keep the code understandable and explain the important logic.
