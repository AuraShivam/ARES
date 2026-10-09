# ARES

ARES (Autonomous Resilient Enterprise Supply Chain) is a hackfest MVP for supply-chain visibility and disruption response. This repository contains a Django REST API and a React dashboard.

## Current scope

- Django REST CRUD APIs for suppliers, materials, inventory, purchase orders, shipments, and disruptions.
- A transparent, rule-based risk assessment endpoint that explains its score and proposes reviewable actions.
- React dashboard for network metrics, operational records, disruption assessment, and creating disruption records.
- SQLite for local development. The HANA system described by the team has not been externally verified, so no HANA connection is attempted or configured.

Recommendations are advisory. This MVP does not write to SAP or autonomously execute procurement/logistics actions.

## Run locally

Backend (from this directory):

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Frontend (in another terminal):

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm run dev
```

Open the Vite URL shown in the terminal. The dashboard expects the API at `http://127.0.0.1:8000/api`; set `VITE_API_BASE_URL` if the backend runs elsewhere.

## API overview

- `GET/POST /api/suppliers/`, `/api/materials/`, `/api/inventory/`, `/api/purchase-orders/`, `/api/shipments/`, `/api/disruptions/`
- `GET /api/overview/` for dashboard totals and open disruptions
- `POST /api/risk/assess/` with `{ "disruption_id": "<uuid>" }` or `{ "title": "...", "severity": "high", "description": "...", "affected_region": "..." }`
- `GET /api/health/`

The default API is intended for a local hackfest demo. Add authentication, authorization, and deployment security controls before exposing it beyond a trusted development environment.

## HANA integration status

HANA connectivity is not established. Before adding a HANA adapter, verify an approved external endpoint, network route, TLS requirements, account permissions, and a supported client/driver with the SAP administrator. Store any approved credentials outside source control. Keep local SQLite available as a development fallback until an integration is verified.
