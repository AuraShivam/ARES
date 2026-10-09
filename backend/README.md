# ARES

ARES (Autonomous Resilient Enterprise Supply Chain) is a hackfest MVP for supply-chain visibility and disruption response. This repository contains a Django REST API and a React dashboard.

For repository-level orientation, see the [architecture guide](../docs/architecture.md) and [delivery roadmap](../docs/roadmap.md).

## Current scope

- Django REST APIs for suppliers, materials, warehouses, inventory, purchase orders and their line items, shipments, disruptions, inventory movements, and audit history.
- A scheduled GDACS connector that ingests global recent disaster alerts, deduplicates source events, and reports feed freshness and sync results.
- A transparent, rule-based risk assessment endpoint that stores explainable assessment history, reassesses material GDACS event changes, and maintains threshold, deduplicated, cooldown-aware advisory alerts.
- Approver-reviewed incident outcomes and a descriptive report for comparing historical labels with the latest risk scores.
- An idempotent email outbox for risk and response-plan events, plus audited dry-run and explicitly approved webhook execution for selected response actions.
- Responsive React dashboard for network signals, operational records, disruption assessment, creating disruptions and multi-line purchase orders, recording inventory movements, and previewing/committing validated CSV imports.
- PostgreSQL stores ARES application data. The MVP supports records entered through its APIs, dashboard forms, and demo-data command.

Risk recommendations are advisory. A configured webhook can run only for a selected action after plan approval, a separate approver execution request, and an explicit environment-level enable flag.

## Run locally

Backend (from this directory):

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
# Edit .env with the PostgreSQL database and account provisioned for your environment.
# Django does not read .env automatically; export its values in this shell:
set -a
source .env
set +a
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
```

In a separate backend terminal, run the public disaster feed once with `python manage.py sync_gdacs_alerts`, or poll continuously with `python manage.py sync_gdacs_alerts --watch`. The connector uses no API credential. GDACS refreshes its standard feed about every six minutes; ARES enforces that minimum polling interval. Configure `ARES_GDACS_MIN_ALERT_LEVEL` as `green`, `orange`, or `red` (default `orange`) and `ARES_GDACS_POLL_INTERVAL_SECONDS` (default `360`) in the backend environment. The Data onboarding page shows the latest feed status; `GET /api/feeds/status/` returns the same status to authenticated users.

Risk alerts default to score `60` with a `60` minute cooldown. Set `ARES_RISK_ALERT_SCORE_THRESHOLD` (0–100) and `ARES_RISK_ALERT_COOLDOWN_MINUTES` in the backend environment to change those values. Alerts are persisted and shown in the dashboard.

Response/risk emails are queued in the database and are not sent unless `ARES_EMAIL_DELIVERY_ENABLED=true`. Configure `ARES_NOTIFICATION_FROM_EMAIL`, `ARES_NOTIFICATION_OPERATIONS_EMAILS`, and the `EMAIL_*` provider values in the ignored local `.env` or deployment secret store, then run `python manage.py dispatch_notifications`. The command can be scheduled by a worker; Phase 8 covers hosted scheduling and monitoring. Submissions go to users in `ares_approvers`/staff who have email addresses; decisions and task updates go to the plan creator and configured operations recipients. Missing recipients are recorded as unroutable.

Response action items default to manual tasks. For a webhook action, configure `ARES_ACTION_WEBHOOK_URL` and its exact hostname in `ARES_ACTION_WEBHOOK_ALLOWED_HOSTS`; keep any `ARES_ACTION_WEBHOOK_TOKEN` in the ignored local `.env` or deployment secret store. Live execution also requires `ARES_ACTION_EXECUTION_ENABLED=true`, an approved and active response plan, an approver request with explicit confirmation, and an `Idempotency-Key` header. Dry-run is the default and performs no side effect. Do not put credentials in action payloads.

Frontend (from the repository root, in another terminal):

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm run dev
```

Open the Vite URL shown in the terminal. The dashboard expects the API at `http://127.0.0.1:8000/api`; set `VITE_API_BASE_URL` if the backend runs elsewhere.

PostgreSQL 14 or newer must be available before running migrations. Configure `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT` using values from your local PostgreSQL setup or database administrator. Leave `POSTGRES_HOST` blank to use the local Unix socket; only set `POSTGRES_SSLMODE` when your database administrator specifies a TLS mode. Never commit `.env` or place real credentials in `.env.example`.

The dashboard includes searchable and sortable views for the supply-chain records, CSV export for the current view, and forms for disruption intake, purchase-order creation, and inventory receipts/issues/adjustments. The CSV import screen supports downloadable templates, row validation, duplicate handling, and a review step before committing. Assessment scores show their factors and advisory recommendation before a user can mark the disruption under review.

## Authentication and access

All API routes require an authenticated account except `GET /api/health/` and `POST /api/auth/login/`. Create the first administrator with `python manage.py createsuperuser`; administrators can create standard users and manage the `ares_approvers` group in Django Admin. Assign approval rights by adding a user to that group. Staff and superuser accounts can also approve or reject response plans. Review decisions record the authenticated account identity; clients cannot choose the reviewer name.

The React app signs in through `/api/auth/login/`, keeps the API token in the current browser tab's session storage, and expires tokens after eight hours by default. Logout revokes the account's active API token. Configure `ARES_API_TOKEN_TTL_HOURS` to change the lifetime. Login attempts are rate limited. `python manage.py test supply_chain.tests` runs the backend API and workflow coverage.

For a trusted local demo, `.env.example` sets `DJANGO_DEBUG=true` and Django uses a development-only fallback secret if none is supplied. Before deploying, set `DJANGO_DEBUG=false`, provide a strong unique `DJANGO_SECRET_KEY`, configure `DJANGO_ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS`, and serve through HTTPS. `DJANGO_SECURE_SSL_REDIRECT` and `DJANGO_SECURE_HSTS_SECONDS` are available for HTTPS deployments; enable them only after the TLS endpoint is correctly configured. Do not reuse the development fallback secret.

## API overview

- CRUD: `/api/suppliers/`, `/api/materials/`, `/api/warehouses/`, `/api/inventory/`, `/api/purchase-orders/`, `/api/shipments/`, `/api/disruptions/`
- `GET /api/purchase-order-lines/` lists normalized order lines. Create or replace lines through the nested `lines` array on a purchase order; an omitted line number is assigned from its position. Existing line IDs and received quantities are retained when a line number is reused.
- `POST /api/inventory-movements/` records a receipt, issue, or adjustment and atomically updates that inventory balance. Receipts need a positive `quantity_delta`, issues a negative one, and adjustments may be positive or negative. A movement that would make stock negative is rejected.
- `GET /api/audit-events/` lists before/after snapshots for direct API create, update, and delete operations. It is read-only through the API.
- Inventory accepts either a `warehouse` ID or the legacy `location` label. Location-only requests continue to work and receive a stable generated warehouse record.
- `GET /api/overview/` for dashboard totals and open disruptions
- `POST /api/risk/assess/` with `{ "disruption_id": "<uuid>" }` or `{ "title": "...", "severity": "high", "description": "...", "affected_region": "..." }`. The response includes a point breakdown, linked evidence coverage, data gaps, and an advisory recommendation.
- `GET /api/risk/assessments/` lists stored assessment snapshots; filter with `?disruption_id=<uuid>`.
- `GET /api/risk/alerts/?status=active` lists current threshold alerts. `GET /api/risk/policy/` returns the effective alert threshold, cooldown, and risk bands.
- `POST /api/risk/outcomes/` records or corrects a verified incident outcome. Staff and `ares_approvers` can submit `{ "disruption_id": "<uuid>", "outcome": "impact", "evidence_notes": "..." }`; use `no_impact` for a verified incident with no material supply-chain impact.
- `GET /api/risk/calibration/` and `python manage.py calibrate_risk` summarize observed outcomes by risk band and precision/recall at the alert threshold. This is descriptive, uses only reviewer-entered labels, and does not tune or train the scoring rules.
- `GET /api/health/`
- `GET /api/feeds/status/` returns the GDACS source's last attempt, last success, recent event count, and sync errors.
- `POST /api/auth/login/` accepts `username` and `password`, returning an expiring API token; `GET /api/auth/me/` returns the signed-in user; `POST /api/auth/logout/` revokes the token.
- `GET /api/response-plans/`, `POST /api/response-plans/`, and `GET/PATCH /api/response-plans/<plan-uuid>/` manage plans and their draft action items. A plan create request includes a disruption, plan owner, and at least one owned action.
- `POST /api/response-plans/<plan-uuid>/{submit,approve,reject,start,complete,cancel}/` performs guarded workflow transitions. Approval and rejection require staff or `ares_approvers` membership. See the [response-plan guide](../docs/response-plans.md) for payloads and transition fields.
- `GET /api/response-actions/`, `GET/PATCH /api/response-actions/<action-uuid>/` lists action items and updates their status/outcome while a plan is active. `POST /api/response-actions/<action-uuid>/execute/` accepts `{ "dry_run": true }` by default; live mode requires an approver and the `Idempotency-Key` header.
- `GET /api/notifications/` lists delivery state for the signed-in email recipient; staff and approvers can inspect the full outbox.
- `GET /api/imports/templates/` returns supported CSV headers and upload limits.
- `GET /api/imports/` lists recent import batches; `GET /api/imports/<batch-uuid>/` returns its row-level preview or result.
- `POST /api/imports/preview/` accepts multipart fields `entity_type`, `source_name`, `duplicate_policy`, and `file`; `POST /api/imports/<batch-uuid>/commit/` revalidates and commits an eligible preview atomically.

Purchase order creation supports the original one-material shape (`material`, `quantity`, and `unit_price`) or normalized multiple lines, for example:

```json
{
  "number": "PO-EXAMPLE-1",
  "supplier": "<supplier-uuid>",
  "currency": "USD",
  "lines": [
    { "material": "<material-uuid-1>", "quantity": "4.00", "unit_price": "12.50" },
    { "material": "<material-uuid-2>", "quantity": "2.00", "unit_price": "30.00" }
  ]
}
```

The additive migration assigns warehouses to existing location labels and creates one line for each existing purchase order, preserving the existing purchase-order header fields and API shape.

The API enforces authentication and approver permissions for the response review workflow. Deployment controls, automated security review, production secret management, and HTTPS hosting still need to be configured before exposing the app publicly.

## Data onboarding

See [the import guide](../docs/data-imports.md) for supported columns, natural keys, import order, duplicate policies, blank-cell behavior, and API details. Imports are supported for suppliers, materials, warehouses, inventory balances, purchase orders, shipments, and disruptions. GDACS source events become advisory disruptions and retain provider attribution and source timestamps. They do not prove that a particular supplier, carrier, facility, or route is affected.

The deterministic risk rules combine disruption severity and confidence with linked supplier, shipment, order, material, inventory, region, and source-freshness evidence. From this directory, run `python manage.py evaluate_risk` to see the representative scenarios and their target bands. See [the risk guide](../docs/risk-intelligence.md) for weights, alert behavior, reviewed outcome labels, and limitations; scenario checks are not an empirical prediction-quality benchmark.
