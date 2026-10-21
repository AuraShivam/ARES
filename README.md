# ARES

**Autonomous Resilient Enterprise Supply Chain** is a local-first application for monitoring supply-chain operations, assessing disruption exposure, and planning responses. The current MVP uses a Django REST Framework API, PostgreSQL, a React dashboard, and Redis for live dashboard events.

ARES is a standalone project. It does not require SAP or a direct connection to a company's ERP. Data is entered through the dashboard or authenticated API, imported from validated CSV files, or received from the public GDACS disaster feed.

## What ARES does

- **Maintains supply-chain records:** suppliers, materials, warehouses, inventory balances and movements, purchase orders and lines, shipments, and disruptions.
- **Shows operational status:** the overview summarizes inventory, shipments, active alerts, and open disruptions. Searchable record pages support sorting and CSV export.
- **Assesses disruption risk:** an explainable rules engine combines event severity and confidence with linked supplier, shipment, order, material, inventory, region, and source-freshness evidence. ARES saves assessment history, opens threshold alerts, and reassesses relevant changes.
- **Forecasts shipment delays:** an experimental scikit-learn model trains from completed shipments whose actual dates were verified by an ARES approver. It can report late-delivery probability, delay estimates, supplier trends, and stock-cover context when sufficient verified examples exist.
- **Plans material demand:** an experimental per-material model forecasts demand over 7, 30, and 90 days from dated inventory issue history. It estimates stockout timing, safety stock, and a suggested reorder quantity while accounting for dated open purchase orders. Forecasts are withheld unless that material has at least 60 days of movement history and 10 distinct consumption dates.
- **Coordinates disruption work:** users create response plans and assign action items. Plans move through draft, approval, execution, and completion states; approver decisions and changes are audited. Email delivery and live webhook execution require explicit configuration and approval.
- **Ingests external hazard alerts:** a scheduled GDACS connector imports recent global disaster alerts and reports feed freshness. GDACS reports hazards; it does not confirm that an ARES supplier, route, or facility is affected.
- **Tracks changes and refreshes the dashboard:** direct API changes are audited. Authenticated WebSocket events tell the browser to refresh its data; 30-second polling is the fallback.

## How it works

```text
User → React dashboard → authenticated Django REST API → PostgreSQL
                                ↕
                       Redis live events
                                ↑
                  GDACS and notification workers
```

The browser loads current records through the API. The backend validates requests, applies workflow rules, and stores records in PostgreSQL. Inventory receipts, issues, and adjustments update the on-hand balance and record the movement in one transaction. Historical movement CSV imports preserve the event date without changing today's balance. They can therefore provide input to demand forecasting without corrupting the current inventory total.

Risk rules and both ML models provide **advisory** results. Shipment predictions require approver-verified delivery outcomes. Demand predictions assume the imported issue history is complete and representative. Model confidence is a data-coverage indicator, not a calibrated guarantee. The demo seed does not fabricate shipment labels or movement history, so predictive results may remain unavailable until real, verified records are added.

## Dashboard sections

| Section | Purpose |
| --- | --- |
| Network overview | Snapshot of operational records, low stock, shipments, disruptions, and active risk alerts |
| Risk intelligence | Explainable disruption assessments and alerts, outcome calibration, and shipment-delay outlook |
| Disruptions and response plans | Record disruption events, assign mitigation work, submit plans for approval, and track actions |
| Shipments and purchase orders | Review delivery commitments, supplier links, purchase-order lines, and shipment status |
| Inventory and demand planning | Inspect warehouse balances and movement history; review forecast demand, projected stockouts, and reorder advice |
| Suppliers, materials, and warehouses | Maintain the core network entities used to connect operational records |
| Data onboarding | Download CSV templates, preview and validate imports, commit accepted rows, and inspect GDACS feed freshness |
| Notifications and audit history | Review email delivery state and inspect recorded before/after changes |

## Run the local demonstration

The recommended demo runs on `http://localhost:8080` using Docker Compose, with PostgreSQL and Redis isolated in the local Compose network. Follow the [deployment and operations guide](docs/deployment.md) for Docker Desktop setup, local configuration, administrator creation, demo data, and safe shutdown. The demo is loopback-only; GitHub Pages cannot run the Django API, workers, or PostgreSQL database.

## Repository map

```text
.
├── backend/                 Django REST API, data models, migrations, workers, and ML logic
├── frontend/                React + Vite dashboard
├── docs/                    Architecture, features, setup, security, and operations guides
├── ops/                      PostgreSQL backup and guarded restore scripts
├── compose.demo.yaml         Local demonstration runtime
└── compose.production.yaml   Provider-neutral hosted runtime example
```

## Guides

- [Architecture and request flow](docs/architecture.md)
- [Backend setup and API reference](backend/README.md)
- [Shipment and disruption risk intelligence](docs/risk-intelligence.md)
- [Demand forecasting and inventory planning](docs/demand-forecasting.md)
- [CSV imports and external data](docs/data-imports.md)
- [Response plans and approvals](docs/response-plans.md)
- [Security and quality](docs/security-quality.md)
- [Deployment, backups, and recovery](docs/deployment.md)
- [Project roadmap and current phase status](docs/roadmap.md)
