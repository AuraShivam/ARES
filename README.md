# ARES

**Autonomous Resilient Enterprise Supply Chain** is a local-first application for monitoring supply-chain operations, assessing disruption exposure, and planning responses. The current MVP uses a Django REST Framework API, PostgreSQL, a React dashboard, and Redis for live dashboard events.

ARES is a standalone project. It does not require SAP or a direct connection to a company's ERP. Data is entered through the dashboard or authenticated API, imported from validated CSV files, or received from the public GDACS disaster feed.

## What ARES does

- **Maintains supply-chain records:** suppliers, materials, warehouses, inventory balances and movements, purchase orders and lines, shipments, and disruptions.
- **Shows operational status:** the overview summarizes inventory, shipments, active alerts, and open disruptions. Searchable record pages support sorting and CSV export.
- **Maps network activity:** the World map plots endpoint connectors and optional source-attributed shipment paths, plus active GDACS points and validated source polygons with alert metadata. A direct connector is not a carrier route, and GDACS hazard presence alone does not establish a supplier or shipment impact.
- **Explores a supply-chain digital twin:** a live graph connects suppliers, materials, warehouses, purchase orders, shipments, and disruptions from PostgreSQL records. Its geographic view uses recorded coordinates and current GDACS source geometry; missing coordinates remain visibly unavailable.
- **Analyzes disruption exposure and what-if scenarios:** evidence distinguishes explicit operator-linked disruption, polygon intersection, policy-buffer proximity, indirect supply-chain dependency, unaffected, and unknown classifications. Supplier/warehouse failure, shipment delay, route disruption, material shortage, and demand surge simulations are saved separately and do not change operational records.
- **Assesses disruption risk:** an explainable rules engine combines event severity and confidence with linked supplier, shipment, order, material, inventory, region, and source-freshness evidence. ARES saves assessment history, opens threshold alerts, and reassesses relevant changes.
- **Forecasts shipment delays:** an experimental scikit-learn model trains from completed shipments whose actual dates were verified by an ARES approver. It can report late-delivery probability, delay estimates, supplier trends, and stock-cover context when sufficient verified examples exist.
- **Plans material demand:** an experimental per-material model forecasts demand over 7, 30, and 90 days from dated inventory issue history. It estimates stockout timing, safety stock, and a suggested reorder quantity while accounting for dated open purchase orders. Forecasts are withheld unless that material has at least 60 days of movement history and 10 distinct consumption dates.
- **Evaluates model quality through the API, CLI, and AI Control Center:** authenticated chronological evaluation runs compare shipment-delay and demand forecasts with simple baselines, report holdout metrics and probability diagnostics, and persist data fingerprints. Evaluation does not alter operational records or automatically calibrate live predictions.
- **Coordinates disruption work:** users create response plans and assign action items. Plans move through draft, approval, execution, and completion states; approver decisions and changes are audited. Email delivery and live webhook execution require explicit configuration and approval.
- **Ingests external hazard alerts:** a scheduled GDACS connector imports recent global disaster alerts and reports feed freshness. GDACS reports hazards; it does not confirm that an ARES supplier, route, or facility is affected.
- **Tracks changes and refreshes the dashboard:** direct API changes are audited. Authenticated WebSocket events tell the browser to refresh its data; 30-second polling is the fallback.
- **Runs optional AI-assisted analysis:** the AI Control Center shows measured data readiness and lets users launch authenticated, bounded specialists through role-limited read-only tools. A coordinator can combine selected specialist reports into an evidence-checked summary for a disruption and exact risk assessment. A human can hand a selected recommendation into an audited response-plan draft, which still follows the existing approver workflow. The provider is disabled by default; explicit configuration is required before questions and selected records can be sent externally.

## How it works

```text
User → React dashboard → authenticated Django REST API → PostgreSQL
                                ↕
              Redis live events + change sequence ledger
                                ↑
       GDACS, change-retry, and notification workers
```

The browser loads current records through the API. The backend validates requests, applies workflow rules, and stores records in PostgreSQL. Inventory receipts, issues, and adjustments update the on-hand balance and record the movement in one transaction. Historical movement CSV imports preserve the event date without changing today's balance. They can therefore provide input to demand forecasting without corrupting the current inventory total.

Risk rules and both ML models provide **advisory** results. Shipment predictions require approver-verified delivery outcomes. Demand predictions assume the imported issue history is complete and representative. Model confidence is a data-coverage indicator, not a calibrated guarantee. The demo seed does not fabricate shipment labels or movement history, so predictive results may remain unavailable until real, verified records are added.

## Dashboard sections

| Section | Purpose |
| --- | --- |
| Network overview | Snapshot of operational records, low stock, shipments, disruptions, and active risk alerts |
| World map | Recorded endpoints, optional supplied shipment routes, and current GDACS event points/polygons with source metadata |
| Supply chain digital twin | Live dependency graph, geographic locations/hazards, impact reasons, health KPIs, isolated simulations, and saved scenario history |
| AI control center | Data readiness, bounded evidence-backed agent runs, execution history, and chronological shipment/demand model evaluations |
| Risk intelligence | Explainable disruption assessments and alerts, shipment predictions, human-reviewed AI response briefings, captured outcomes, calibration summaries, and reviewed response-plan effectiveness |
| Disruptions and response plans | Record disruption events, assign mitigation work, submit plans for approval, and track actions |
| Shipments and purchase orders | Review delivery commitments, supplier links, purchase-order lines, and shipment status |
| Inventory and demand planning | Inspect warehouse balances and movement history; review forecast demand, projected stockouts, and reorder advice |
| Suppliers, materials, and warehouses | Maintain the core network entities used to connect operational records |
| Data onboarding | Download CSV templates, preview and validate imports, commit accepted rows, and inspect GDACS feed freshness |
| Notifications and audit history | Review email delivery state and inspect recorded before/after changes |

## Run the local demonstration

The recommended demo runs on `http://localhost:8080` using Docker Compose, with PostgreSQL and Redis isolated in the local Compose network. Follow the [local demo walkthrough](docs/operations/demo-walkthrough.md) for a presenter flow and the [deployment and operations guide](docs/operations/deployment.md) for setup, operations, backup, recovery, and safe shutdown. The demo is loopback-only; GitHub Pages cannot run the Django API, workers, or PostgreSQL database.

## Repository map

```text
.
├── backend/                 Django REST API, data models, migrations, workers, and ML logic
├── frontend/                React + Vite dashboard
├── docs/
│   ├── engineering/          Architecture, security, and testing guides
│   ├── operations/           Local demo walkthrough, deployment runbook, and roadmap
│   ├── product/              Feature and data onboarding guides
│   └── references/           Historical project documents (local PDFs ignored by Git)
├── ops/                     PostgreSQL backup and guarded restore scripts
├── compose.demo.yaml         Local demonstration runtime
└── compose.production.yaml   Provider-neutral hosted runtime example
```

The ignored `.local/archive/legacy-sap-purchase-order-project/` folder preserves old local SQLite-era files. It is not used by the PostgreSQL-backed ARES app and is not part of the Git repository.

## Guides

- [Architecture and request flow](docs/engineering/architecture.md)
- [Supply-chain digital twin](docs/engineering/digital-twin.md)
- [Backend setup and API reference](backend/README.md)
- [Shipment and disruption risk intelligence](docs/product/risk-intelligence.md)
- [Demand forecasting and inventory planning](docs/product/demand-forecasting.md)
- [CSV imports and external data](docs/product/data-imports.md)
- [Response plans and approvals](docs/product/response-plans.md)
- [Security and quality](docs/engineering/security-quality.md)
- [Testing guide](docs/engineering/testing.md)
- [Deployment, backups, and recovery](docs/operations/deployment.md)
- [Local demo walkthrough and presenter flow](docs/operations/demo-walkthrough.md)
- [Agent runtime, provider setup, and data boundaries](docs/engineering/agentic-ai-foundation.md)
- [Project roadmap and current phase status](docs/operations/roadmap.md)
- [Historical reference documents](docs/references/README.md)
