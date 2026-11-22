# HarborShift

HarborShift is a local student prototype for simulating port disruptions, tracing shipment and manufacturing delays, and comparing recovery options. The source data, manufacturing demo, schedules, freight, and penalties are synthetic. Public advisories appear separately for review.

## Start on Windows

Use Python 3.11 or newer and Node.js 22.12 or newer. From PowerShell in the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
```

Start the API in the same terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In a second PowerShell terminal in the project folder:

```powershell
npm.cmd --prefix frontend run dev -- --port 5173 --strictPort
```

Open [the dashboard](http://127.0.0.1:5173) or [the API reference](http://127.0.0.1:8000/docs). The default dashboard opens with the baseline manufacturing chain. Select **Apply event** to run E001 or **Reset** to return to the baseline. Dependency installation requires package access. The simulator and dashboard run locally afterward without public feeds or a paid API.

## Run demonstrations from the CLI

Use the virtual environment Python explicitly, or activate it and substitute `python`.

```powershell
.\.venv\Scripts\python.exe main.py validate
.\.venv\Scripts\python.exe main.py neighbors P01
.\.venv\Scripts\python.exe main.py route P03 P11 --quantity 10 --units-per-container 10 --close-port P05
.\.venv\Scripts\python.exe main.py simulate --manufacturing --as-of 2027-01-05 --event E001
.\.venv\Scripts\python.exe main.py simulate --manufacturing --as-of 2027-01-05
.\.venv\Scripts\python.exe main.py simulate --as-of 2027-01-18 --event E004 --shipment SH044 --recover --use-ml
```

The routing demonstration compares 12 days and INR 216,000 via Durban against 32 days and INR 576,000 when Durban is closed. It assumes one container. `--objective cheapest` minimizes freight. Repeat `--via` to require stops in order, or `--close-port` and `--close-route` for multiple closures. A valid query with no path reports the reason. Add `--data "path"` after a CLI command to use another CSV directory or archive.

For a manual event, specify `--port P11 --event-type strike --duration 7 --severity 4 --status closed` after `simulate --as-of 2027-01-18`. The event starts on the simulated date unless `--start YYYY-MM-DD` is supplied. Repeat `--event` to combine sample events. A scenario with no events shows the baseline.

## Data and simulation assumptions

- The original ZIP is read directly. It contains 20 ports, 50 directed routes, 100 shipments, 232 legs, and 2,000 synthetic historical delay records. The validator reports zero blocking errors and four warnings. D001 lists PR03 but SH001 carries PR04 and starts at P01. D002 lists PR04 but SH003 carries PR05 and starts at P02. Both dependencies specify manufacturing at P05 and are quarantined.
- The manufacturing fixture is documented in `data/fixtures/manufacturing.json`. It uses Savannah → Durban raw-material shipment DEMO-RAW, a four-day production task, Durban → Mumbai finished-parts shipment DEMO-FINISHED, and contract DEMO-CUSTOMER. The source route times are used. The January dates, quantity of 10 units, packing assumption of 10 units per container, INR 24,000 original raw purchase, local supplier, contract links, and penalty are derived demo values.
- An event uses a calendar interval from start through the day before reopening. Port calls are scheduled departures and arrivals, with same-day transfers treated as one call. The simulator assumes past calls are complete, labels future contacts as potential exposure, and keeps sailing time fixed. Connection slack can absorb port delays. Closures wait for reopening. The rule-based restriction wait is half the severity rounded up and capped at the remaining event days.
- New recovery routes use a conservative planning window and avoid disruptive ports. Route capacity is illustrative residual capacity for one shipment. Loads use ceiling division. Reroutes from an uncertain in-transit decision point are conditional. Local sourcing assumes zero sea freight and uses supplier lead time and port availability. Supplier options cover the full quantity from a qualified source. The manufacturing fixture retains the factory in every recommendation and compares recovery at the raw handoff when both shipments are disrupted.
- An on-time option ranks ahead of a late one. On-time options rank by comparable future cost and then ETA. Late options rank first by penalty, then by comparable cost and ETA. Where some purchase costs are missing, ETA replaces cross-option cost comparisons. Exact ties favor keeping the current itinerary. Existing purchase commitments and cancellation fees are unknown. Shared capacity allocation, multi-supplier splits, time-dependent route search, and live vessel positions are outside this prototype.

## Delay model

Train with `.\.venv\Scripts\python.exe -m harborshift.ml.train`. The reproducible split uses seed 42 and 1,400 training, 300 validation, and 300 test rows. One-hot encoding and scaling are fitted on training data. The comparison includes a mean baseline, linear regression, random forest, and gradient boosting.

Validation selected linear regression. Its held-out synthetic MAE was **1.147 days** and RMSE was **1.446 days**, compared with **3.317** and **3.961 days** for the mean baseline. The model and report are in `artifacts/`. Only load local model artifacts you trust. Its results describe the supplied synthetic data. For operational evaluation, use verified planned and actual arrival dates, time-correct disruption inputs, and chronological validation.

Synthetic ML replaces the rule estimate for restricted calls when selected and available. Closure waits still follow the reopening rule. With an absent model the simulator uses the offline rule. Congestion and buffer are explicit scenario inputs that default to zero.

## API examples

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/simulate -Method Post -ContentType 'application/json' -Body '{"as_of":"2027-01-05","manufacturing":true,"sample_ids":["E001"]}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/route -Method Post -ContentType 'application/json' -Body '{"origin":"P03","destination":"P11","quantity_units":10,"units_per_container":10,"closed_ports":["P05"]}'
```

Each request starts a fresh scenario. `/ports`, `/routes`, `/shipments`, and `/disruptions` expose the validated source records. `/health` checks dataset readiness. Dates use ISO format and monetary amounts are numeric INR.

## Public advisories

The Disruptions tab fetches official [UK Maritime and Coastguard Agency](https://www.gov.uk/search/news-and-communications?organisations%5B%5D=maritime-and-coastguard-agency) and [NOAA National Hurricane Center](https://www.nhc.noaa.gov/aboutrss.shtml) feeds on request. Fetches use timeouts and a ten-minute cache. Results are deduplicated by normalized URL or title and publication-time hash. Extraction requires a disruption keyword and maritime context, with explicit port aliases used for matching. Multiple possible matches, missing duration, and missing severity remain unknown. A failed feed leaves the simulator available.

An unambiguous candidate can be reviewed as a simulated replay. The user supplies the fictional date, duration, and severity. Publication times are retained with the advisory and are never mapped automatically onto the January 2027 sample.

## Tests and demonstration

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
$env:HARBORSHIFT_BROWSER_CHANNEL = 'msedge'
$env:Path = "$((Resolve-Path .venv\Scripts).Path);$env:Path"
npm.cmd --prefix frontend run test:e2e
```

Stop manually started API and Vite sessions before the browser tests, which start their own servers. The test command can use installed Edge on Windows or Playwright Chromium. For Chromium, omit the Edge environment variable and run the frontend package's `npx playwright install chromium` once.

The [3–5 minute demonstration](docs/DEMO.md) includes the walkthrough, algorithm complexity, verification checks, and desktop/mobile screenshots. `HARBORSHIFT_IMPLEMENTATION_PLAN.md` records the milestone checklist.

| Path | Purpose |
|---|---|
| `harborshift/` | Data validation, graph and routing, disruption simulation, dependency scheduling, and recovery |
| `harborshift/ml/` and `artifacts/` | Training, prediction, model, and held-out evaluation |
| `harborshift/news/` | Public advisory collection and extraction |
| `api/` and `frontend/` | FastAPI service and React dashboard |
| `harber_shift_sample_datasets/` | Original synthetic dataset ZIP |
| `data/fixtures/` | Derived manufacturing fixture |
| `tests/` and `frontend/tests/` | Python and browser verification |
