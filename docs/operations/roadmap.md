# ARES delivery roadmap

ARES is planned as a standalone PostgreSQL-backed supply-chain visibility and resilience application. Phase status describes the current local MVP and does not imply production readiness.

| Phase | Scope | Status |
| --- | --- | --- |
| 0. Project foundation | Django, React, PostgreSQL, repository organization, and local setup | Complete locally; PostgreSQL 17 is running and existing ARES records were imported |
| 1. Supply-chain domain and APIs | Suppliers, materials, inventory, purchase orders, shipments, and disruptions | MVP complete |
| 2. Operational workflows | Inventory movement, audit history, overview, demo data, and API workflows | MVP complete |
| 3. Data onboarding and quality | Manual entry, bulk imports, validation, data provenance, and live source ingestion | Complete locally: CSV imports cover all domain records; migrations are applied to PostgreSQL; the GDACS GeoJSON API connector persists current source events and triggers risk assessments/alerts. GDACS is disaster data, not supplier/carrier telemetry. Continuous scheduling belongs to Phase 8; additional supplier/carrier feeds need their own source selection and integration. |
| 4. Risk intelligence and prediction | Explainable risk evidence, shipment-delay prediction, demand forecasting, event-triggered reassessment, threshold alerts, and outcome-based evaluation | Existing risk MVP is locally verified. Experimental shipment-delay and material-demand models are implemented; demand planning includes dated movement imports, 7/30/90-day forecasts, stockout outlook, and advisory reorder/safety-stock estimates. The new movement migration and API still need local runtime verification, and forecasts remain unavailable per material until at least 60 days and 10 distinct issue dates exist. Real-world model accuracy is not established. |
| 5. Disruption response | Reviewable response plans, ownership, approvals, tracking, notifications, and controlled actions | MVP complete and locally checked: an idempotent email outbox routes plan/risk updates to approvers, plan creators, and configured operations recipients with retry tracking; response actions support audited dry-runs and an allowlisted HTTPS webhook behind plan approval, separate approver execution, and an explicit global enable flag. Django's system check is clean, and the dispatcher confirmed email remains disabled by default without changing queued rows. SMTP/recipients/webhook values must be configured locally or in deployment; the notification command needs scheduling for continuous delivery (Phase 8). |
| 6. React dashboard | Operational overview, records, risk assessment, forms, and live updates | MVP complete: authenticated WebSocket invalidation events refresh current API data; the 30-second visible-tab polling remains as a fallback and refreshes immediately when the tab returns. Overview, records, risk intelligence, response plans, imports, operational forms, search/sort, and CSV export are implemented. The frontend production build previously succeeded; the WebSocket addition still needs a browser/runtime check. |
| 7. Security and quality | Automated coverage, access controls, robust errors, and connector/event reliability | Existing API and frontend regression coverage remains complete for the previously verified workflows: all 13 backend tests and 4 frontend tests passed before Phase 8 changes. WebSocket token expiry, reconnect, and post-commit delivery need dedicated coverage; the new socket code has not been exercised in this environment. See the [test guide](../engineering/testing.md). |
| 8. Deployment and operations | Local demonstration, production API and worker deployment, event delivery, backups, monitoring, and recovery | Local and production Compose packages, ASGI WebSockets with Redis, TLS proxy, production settings, background workers, validated PostgreSQL backup/retention, guarded restore script, and runbook are implemented. The local stack is not verified because Docker/Podman is unavailable here. No live production host is planned. Off-host backup and provider alert setup apply only if ARES is later hosted. |
| 9. Supply-chain digital twin | Dynamic dependency graph, coordinates/GeoJSON, impact propagation, what-if simulations, ordered sync recovery, React control-tower UI, and technical documentation | Implemented in source with an additive `0012_digital_twin` migration. Frontend production build and Python syntax checks pass. Backend API/database tests and an authenticated screenshot are pending because this environment lacks the installed Django Channels/Daphne dependencies and a running Docker daemon. No production records or coordinates were fabricated. |

## Recommended order

1. Choose supplier/carrier feed providers only if their data will improve risk decisions; get provider integration details and add source-specific reliability coverage.
2. For local email delivery, configure SMTP only when a demo requires it; outbound response actions remain disabled by default.
3. Run the local demonstration by following the [deployment and operations guide](deployment.md). Use GitHub for source, pull requests, and build automation; GitHub Pages cannot host ARES's Django API and PostgreSQL database.

## Agentic AI and resilience-intelligence expansion

This workstream follows the requirements in the master development prompt and extends the existing product phases above.

| AI work phase | Scope | Status |
| --- | --- | --- |
| 1. Data readiness and shared contracts | Read-only data readiness API; explicit coverage, provenance, freshness, and model data gaps; validated, provider-neutral agent result contract | Implemented locally; focused tests are added but could not run because the current backend virtual environment is missing `daphne`; see [agentic AI foundation](../engineering/agentic-ai-foundation.md) |
| 2. Agent runtime and provider abstraction | Configurable provider, disabled/unavailable state without credentials, execution lifecycle and read-only tools | Not started |
| 3. Specialist agents and coordinator | Risk, supplier, inventory, logistics, procurement agents with structured coordination | Not started |
| 4. Predictive model evaluation | Chronological baselines/comparison, calibration, reproducible evaluation and persisted metrics | Partially implemented; current models remain experimental |
| 5. Disaster and geospatial exposure | Improve source event lifecycle/geometry handling and evidence-based exposure paths | Partially implemented; route and facility data gaps remain |
| 6. Recovery strategy simulation | Compare verified supplier, stock redistribution, emergency procurement and route options in isolated simulations | Partially implemented; current simulator is basic and options depend on missing data |
| 7. Outcome tracking and calibration | Connect predictions, approved actions, verified outcomes and effectiveness reporting | Partially implemented; labels are limited and reviewer supplied |
| 8. Human-reviewed end-to-end coordination | Orchestrate disruption-to-recommendation workflow and approval handoff | Partially implemented; response plan approvals exist, agent workflow does not |
| 9. Agentic and predictive dashboard | Agent control centre, model evaluation, enhanced simulation views | Not started |
| 10. Integrated reliability and governance | Agent-specific security, timeouts/retries, audit, prompt/model governance and complete integration coverage | Partially implemented at core-platform level |
| 11. Documentation and demonstration | End-to-end architecture, provider configuration, operations runbook and demonstration flow | Partially implemented; Phase 1 contract/readiness docs added |

The measured requirements for supplier alternatives, shipment routes, and training history are listed by `GET /api/ai/data-readiness/`. Existing ARES capabilities are reused; this expansion does not replace the risk rules, current forecast implementations, or digital twin.

## Immediate next step

Apply migration `0012_digital_twin` in the configured local PostgreSQL environment, then run `python manage.py test supply_chain.tests` and the Compose demo. Add verified coordinates for the supplier/warehouse/disruption records used in the demonstration; missing coordinates remain unavailable by design. Test a current source-provided GDACS event and one simulation, then capture screenshots from that authenticated run. Do not use country/region name matches as evidence of exposure, and do not present a what-if result as an operational prediction.
