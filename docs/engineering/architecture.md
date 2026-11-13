# ARES architecture

## System overview

ARES is a standalone supply-chain application with a Django REST API, PostgreSQL database, and React dashboard.

```text
Browser
  └── React + Vite dashboard (frontend/)
       ├── HTTP /api requests ──> Django REST API (ASGI / Daphne)
       └── authenticated WebSocket <── Redis event groups
                                      ↑
                 ┌────────────────────┴─────────────────┐
                 │ Django API and background workers    │
                 ├── supply_chain models and REST API   │
                 ├── explainable risk rules and ML forecasts │
                 ├── digital-twin graph/impact/simulation│
                 ├── disruption plans and audit trail   │
                 └── GDACS, retry, and notification workers │
                           │                 │
                       PostgreSQL          Redis
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
| `backend/supply_chain/demand_forecast.py` | Experimental per-material demand forecasts and advisory stock planning |
| `backend/supply_chain/digital_twin/` | Database-derived graph, GeoJSON, impact propagation, health KPIs, and isolated what-if scenarios |
| `backend/supply_chain/agents/` | Bounded specialist and sequential coordinator workflows, OpenAI Responses provider adapter, validated structured output, and role-scoped read-only tools |
| `backend/supply_chain/agentic_data_readiness.py` | Read-only operational-data coverage report used to show prerequisites, missing evidence, and whether agent-provider configuration is present |
| `backend/supply_chain/migrations/` | Versioned database schema changes |
| `frontend/src/app/` | Dashboard shell, screen state, API orchestration, and user actions |
| `frontend/src/config/` | Navigation and table field configuration |
| `frontend/src/features/` | Overview widgets, record tables, and action dialogs |
| `frontend/src/lib/` | Shared API request and display formatting helpers |
| `docs/` | Architecture and delivery roadmap |

## Data and request flow

1. Django routes API requests from `backend/config/urls.py` to handlers in `backend/supply_chain/views.py`.
2. Serializers validate request data and represent model relationships.
3. Django ORM reads and updates PostgreSQL. Live inventory movements update a balance and write the movement record in one transaction; imported historical movements preserve their business event date without changing today's balance.
4. Risk assessment combines disruption severity and reported confidence with linked supplier, shipment, open purchase-order, material, inventory, region, and source-freshness evidence. It returns a capped score, point breakdown, coverage summary, data gaps, and advisory recommendation.
5. The optional authenticated agent runtime reads only through role-limited tools, validates specialist evidence against tool results, records each workflow stage, and synthesizes a coordinator result from those specialist reports. It sends the question and selected read-only ARES records to an external provider only when an operator configures it and explicitly enables external processing.
6. The React dashboard calls `/api/` and renders overview metrics, tables, and forms. An agent dashboard is later-phase work.

## Dashboard refresh behavior

The authenticated dashboard opens a same-origin WebSocket at `/ws/events/` and authenticates with its expiring API token in the first message, not in the URL. For graph-relevant changes, Django writes a monotonically increasing change sequence and broadcasts resource/action/sequence metadata after the database change. The socket never sends record contents. Redis shares event groups among Daphne and workers; `retry_digital_twin_events` retries pending publishes. Clients recover with `GET /api/digital-twin/changes/?since=<sequence>`. The browser reconnects with backoff and retains 30-second visible-tab polling as a fallback. A relative timestamp reports the last successful refresh; API failures mark displayed data stale.

## Data sources and database

PostgreSQL is ARES's system of record. `backend/config/settings.py` reads connection settings from `POSTGRES_*` environment variables. Local credentials belong in the ignored `backend/.env`; `.env.example` contains blank credential fields.

The MVP receives data through its APIs, dashboard workflows, the demo seed command, validated CSV imports for all domain records, and a scheduled connector for the public GDACS current-events GeoJSON API. CSV previews record batch and row provenance; commits revalidate data and apply the whole batch in one transaction. The GDACS connector reads the API's bounded recent-events collection, normalizes significant alerts, deduplicates source events, retries temporary upstream failures, updates source freshness, and exposes sync health. Run `python manage.py sync_gdacs_alerts --watch` from `backend/` to poll at the configured interval. GDACS data is disaster-alert context, not supplier/carrier telemetry. The dashboard also supports CSV export.

## Current API surface

- CRUD resources: suppliers, materials, warehouses, inventory, inventory movements, purchase orders, purchase-order lines, shipments, disruptions, and audit events.
- `GET /api/map/data/` provides shipment endpoints with coordinates and active GDACS feed-event points for the authenticated world map.
- The digital twin APIs provide the current relationship graph, GeoJSON locations, health metrics, reasoned disruption propagation, isolated simulations, and sequence-based sync recovery; see the [digital twin guide](digital-twin.md).
- Response workflow: `/api/response-plans/` and `/api/response-actions/`; plan changes and review transitions are written to audit history.
- Access: authenticated API tokens for the dashboard, with the `ares_approvers` group or Django staff status required for approval decisions; `/api/health/` and login are the only public API routes.
- Summary and health: `GET /api/overview/`, `GET /api/health/`.
- Risk assessment: `POST /api/risk/assess/`.
- Risk rules and representative-scenario evaluation: [risk intelligence guide](../product/risk-intelligence.md); run `python manage.py evaluate_risk` from `backend/`.
- CSV onboarding: `GET /api/imports/templates/`, `GET /api/imports/`, `POST /api/imports/preview/`, and `POST /api/imports/<uuid>/commit/`.
- External feed status: authenticated `GET /api/feeds/status/`.
- Agentic APIs: authenticated `GET /api/ai/status/`, `/api/ai/tools/`, and `/api/ai/data-readiness/` report provider configuration, read-only tools, and measured data coverage. `POST /api/ai/executions/` runs a bounded specialist or sequential coordinator workflow when an external provider is explicitly enabled; per-user execution history and individual specialist/synthesis steps are available at `/api/ai/executions/` and `/api/ai/executions/<uuid>/`. See the [agentic AI foundation guide](agentic-ai-foundation.md).
- The dashboard API base defaults to `http://127.0.0.1:8000/api`; set `VITE_API_BASE_URL` to use another API address.

See [backend/README.md](../../backend/README.md) for setup and endpoint details.

## Design boundaries

- Seeded and user-entered records are not verified against external supply-chain systems.
- GDACS alerts indicate natural-disaster events; they do not prove that a specific supplier, shipment, or facility is affected.
- Disruption scores use transparent rules. Experimental shipment-delay and material-demand models train from verified outcomes and dated movements respectively; forecasts are withheld when there is insufficient history and have not been calibrated as probabilities.
- API and WebSocket authentication plus response-plan approval permissions are implemented for the MVP. HTTPS deployment, production secret management, WebSocket regression coverage, and deployment safeguards remain before wider exposure; see [security and quality](security-quality.md).
- Recommendations are advisory; ARES does not autonomously execute procurement or logistics actions.
- Agent-provider integration is disabled by default. When explicitly enabled, selected questions and read-only operational records are sent to the configured provider; execution results are advisory and require human approval. Configuration status does not verify provider reachability.
