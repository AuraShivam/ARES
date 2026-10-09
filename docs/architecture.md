# ARES architecture

## System overview

ARES is a standalone supply-chain application with a Django REST API, PostgreSQL database, and React dashboard.

```text
Browser
  └── React + Vite dashboard (frontend/)
       └── HTTP /api requests
            └── Django REST API (backend/)
                 ├── supply_chain domain models and API
                 ├── explainable risk rules
                 ├── disruption response plans and audit trail
                 ├── scheduled GDACS feed poller
                 └── PostgreSQL
```

## Repository responsibilities

| Path | Responsibility |
| --- | --- |
| `backend/manage.py` | Django management entry point |
| `backend/config/` | Django settings, root routes, WSGI, and ASGI |
| `backend/supply_chain/models.py` | Supplier, material, warehouse, inventory, procurement, shipment, disruption, movement, and audit entities |
| `backend/supply_chain/serializers.py` | API input validation and JSON representation |
| `backend/supply_chain/views.py` | REST endpoints, overview, health, and risk assessment handlers |
| `backend/supply_chain/risk.py` | Explainable deterministic scoring and advisory recommendations |
| `backend/supply_chain/migrations/` | Versioned database schema changes |
| `frontend/src/app/` | Dashboard shell, screen state, API orchestration, and user actions |
| `frontend/src/config/` | Navigation and table field configuration |
| `frontend/src/features/` | Overview widgets, record tables, and action dialogs |
| `frontend/src/lib/` | Shared API request and display formatting helpers |
| `docs/` | Architecture and delivery roadmap |

## Data and request flow

1. Django routes API requests from `backend/config/urls.py` to handlers in `backend/supply_chain/views.py`.
2. Serializers validate request data and represent model relationships.
3. Django ORM reads and updates PostgreSQL. Inventory movements update a balance and write the movement record in one transaction.
4. Risk assessment combines disruption severity and reported confidence with linked supplier, shipment, open purchase-order, material, inventory, region, and source-freshness evidence. It returns a capped score, point breakdown, coverage summary, data gaps, and advisory recommendation.
5. The React dashboard calls `/api/` and renders overview metrics, tables, and forms.

## Dashboard refresh behavior

The authenticated dashboard refreshes the overview and active page every 30 seconds while its browser tab is visible. It pauses background polling when the tab is hidden and fetches fresh data when the user returns. A relative timestamp reports the last successful refresh, and failed refreshes switch the connection indicator to a stale-data state while keeping the last displayed records available. A user can also request an immediate refresh. This provides near-real-time updates; it is not server push. If a deployment needs lower latency, Phase 8 should add authenticated streaming with an ASGI-capable host and an event delivery mechanism appropriate to the deployment's number of instances.

## Data sources and database

PostgreSQL is ARES's system of record. `backend/config/settings.py` reads connection settings from `POSTGRES_*` environment variables. Local credentials belong in the ignored `backend/.env`; `.env.example` contains blank credential fields.

The MVP receives data through its APIs, dashboard workflows, the demo seed command, validated CSV imports for all domain records, and a scheduled connector for the public GDACS global disaster feed. CSV previews record batch and row provenance; commits revalidate data and apply the whole batch in one transaction. The GDACS connector normalizes significant recent alerts, deduplicates source events, retries temporary upstream failures, updates source freshness, and exposes sync health. Run `python manage.py sync_gdacs_alerts --watch` from `backend/` to poll at the configured interval. The provider's recent-events feed is global and refreshed about every six minutes; it is disaster-alert data, not supplier/carrier telemetry. The dashboard also supports CSV export.

## Current API surface

- CRUD resources: suppliers, materials, warehouses, inventory, inventory movements, purchase orders, purchase-order lines, shipments, disruptions, and audit events.
- Response workflow: `/api/response-plans/` and `/api/response-actions/`; plan changes and review transitions are written to audit history.
- Access: authenticated API tokens for the dashboard, with the `ares_approvers` group or Django staff status required for approval decisions; `/api/health/` and login are the only public API routes.
- Summary and health: `GET /api/overview/`, `GET /api/health/`.
- Risk assessment: `POST /api/risk/assess/`.
- Risk rules and representative-scenario evaluation: [risk intelligence guide](risk-intelligence.md); run `python manage.py evaluate_risk` from `backend/`.
- CSV onboarding: `GET /api/imports/templates/`, `GET /api/imports/`, `POST /api/imports/preview/`, and `POST /api/imports/<uuid>/commit/`.
- External feed status: authenticated `GET /api/feeds/status/`.
- The dashboard API base defaults to `http://127.0.0.1:8000/api`; set `VITE_API_BASE_URL` to use another API address.

See [backend/README.md](../backend/README.md) for setup and endpoint details.

## Design boundaries

- Seeded and user-entered records are not verified against external supply-chain systems.
- GDACS alerts indicate natural-disaster events; they do not prove that a specific supplier, shipment, or facility is affected.
- Risk scores use transparent rules; no trained or hosted AI model is currently connected.
- API authentication and response-plan approval permissions are implemented for the MVP. HTTPS deployment, production secret management, UI test coverage, and deployment safeguards remain before wider exposure; see [security and quality](security-quality.md).
- Recommendations are advisory; ARES does not autonomously execute procurement or logistics actions.
