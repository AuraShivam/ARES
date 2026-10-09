# ARES delivery roadmap

ARES is planned as a standalone PostgreSQL-backed supply-chain visibility and resilience application. Phase status describes the current local MVP and does not imply production readiness.

| Phase | Scope | Status |
| --- | --- | --- |
| 0. Project foundation | Django, React, PostgreSQL, repository organization, and local setup | Complete locally; PostgreSQL 17 is running and existing ARES records were imported |
| 1. Supply-chain domain and APIs | Suppliers, materials, inventory, purchase orders, shipments, and disruptions | MVP complete |
| 2. Operational workflows | Inventory movement, audit history, overview, demo data, and API workflows | MVP complete |
| 3. Data onboarding and quality | Manual entry, bulk imports, validation, data provenance, and live source ingestion | Implementation complete: CSV imports cover all domain records; the global GDACS recent-disaster connector normalizes, timestamps, deduplicates, retries, and reports sync health. Its poll interval follows the provider's six-minute feed refresh. The first database migration and live sync still need to run in a Django-configured environment; GDACS is disaster data, not supplier/carrier telemetry. |
| 4. Risk intelligence | Explainable risk evidence, scoring, event-triggered reassessment, threshold alerts, cooldown/deduplication, and outcome-based evaluation | Implementation complete: manual and GDACS-event assessments are persisted with evidence; GDACS changes trigger reassessment; configurable thresholds open/clear deduplicated alert records with escalation/cooldown counters; active alerts appear on the dashboard; approvers can record verified outcomes and run a calibration report. Apply migration `0007` before using the new APIs. Empirical calibration still requires a representative set of verified labels; the report does not train or tune the rules. |
| 5. Disruption response | Reviewable response plans, ownership, approvals, tracking, notifications, and controlled actions | Implementation complete: an idempotent email outbox routes plan/risk updates to approvers, plan creators, and configured operations recipients with retry tracking; response actions support audited dry-runs and an allowlisted HTTPS webhook behind plan approval, separate approver execution, and an explicit global enable flag. SMTP/recipients/webhook values must be configured locally or in deployment; the notification command needs scheduling for continuous delivery (Phase 8). |
| 6. React dashboard | Operational overview, records, risk assessment, forms, and live updates | Local MVP complete: authenticated dashboard data refreshes every 30 seconds while visible, refreshes immediately when the tab returns, and shows relative last-successful-update and stale-data status. Existing manual refresh and workflow forms remain available. This is near-real-time polling; authenticated server-push is deferred to Phase 8 so it can be deployed with an ASGI/event-delivery design instead of holding synchronous API workers open. |
| 7. Security and quality | Automated coverage, access controls, robust errors, and connector/event reliability | MVP implemented: authenticated API, approver permissions, expiring tokens, safer API errors, and backend/frontend utility coverage. Tests need execution in the configured environment. Add coverage for connectors, duplicate/retried events, permissions, alert delivery, and live-stream reconnects; production hardening remains. |
| 8. Deployment and operations | Hosted PostgreSQL, API and worker deployment, event delivery, backups, monitoring, and recovery | Remaining: deploy the API, scheduled/queue workers, and PostgreSQL; add Redis/channel infrastructure only if multi-instance live fan-out requires it; configure TLS and secret management; automate backups and test restores; monitor feed freshness, ingestion lag, worker failures, API health, and live-stream connectivity. |

## Recommended order

1. Apply pending Django migrations (including Phase 4 migration `0007`) and run one GDACS sync in the configured environment; verify source status, assessment history, and any threshold alerts.
2. Add supplier/carrier feeds if the project needs those signals, and assess natural-disaster events against facility and route locations.
3. Run the backend and frontend automated coverage in the configured environment, then add tests for ingestion, event retries, and live updates.
4. Configure the Phase 5 outbox and optional webhook from deployment secrets, schedule `dispatch_notifications`, and add authenticated dashboard streaming if the deployed update-latency requirement is shorter than the 30-second polling interval.
5. Deploy the API and workers with backups, restore checks, monitoring, and recovery procedures; refine dashboard usability along the way.

## Immediate next step

Phase 3 and 4 implementation is in the repository, but the new migrations have not been applied in the configured PostgreSQL environment. Run `python manage.py migrate`, then `python manage.py sync_gdacs_alerts`; verify `/api/feeds/status/`, `/api/risk/assessments/`, and `/api/risk/alerts/?status=active`. For calibration, approvers must first record verified outcomes; `python manage.py calibrate_risk` then reports available labeled history. The always-on poller is a local command for now; managed worker deployment belongs to Phase 8.
