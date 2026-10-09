# ARES

ARES (Autonomous Resilient Enterprise Supply Chain) is a hackfest MVP for supply-chain visibility and disruption response. This repository contains a Django REST API and a React dashboard.

## Current scope

- Django REST APIs for suppliers, materials, warehouses, inventory, purchase orders and their line items, shipments, disruptions, inventory movements, and audit history.
- A transparent, rule-based risk assessment endpoint that explains its score and proposes reviewable actions.
- Responsive React dashboard for network signals, operational records, disruption assessment, creating disruptions and multi-line purchase orders, and recording inventory movements.
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

The dashboard includes searchable and sortable views for the supply-chain records, CSV export for the current view, and forms for disruption intake, purchase-order creation, and inventory receipts/issues/adjustments. Assessment scores show their factors and advisory recommendation before a user can mark the disruption under review.

## API overview

- CRUD: `/api/suppliers/`, `/api/materials/`, `/api/warehouses/`, `/api/inventory/`, `/api/purchase-orders/`, `/api/shipments/`, `/api/disruptions/`
- `GET /api/purchase-order-lines/` lists normalized order lines. Create or replace lines through the nested `lines` array on a purchase order; an omitted line number is assigned from its position. Existing line IDs and received quantities are retained when a line number is reused.
- `POST /api/inventory-movements/` records a receipt, issue, or adjustment and atomically updates that inventory balance. Receipts need a positive `quantity_delta`, issues a negative one, and adjustments may be positive or negative. A movement that would make stock negative is rejected.
- `GET /api/audit-events/` lists before/after snapshots for direct API create, update, and delete operations. It is read-only through the API.
- Inventory accepts either a `warehouse` ID or the legacy `location` label. Location-only requests continue to work and receive a stable generated warehouse record.
- `GET /api/overview/` for dashboard totals and open disruptions
- `POST /api/risk/assess/` with `{ "disruption_id": "<uuid>" }` or `{ "title": "...", "severity": "high", "description": "...", "affected_region": "..." }`
- `GET /api/health/`

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

The default API is intended for a local hackfest demo. Add authentication, authorization, and deployment security controls before exposing it beyond a trusted development environment.

## HANA integration status

HANA connectivity is not established. Before adding a HANA adapter, verify an approved external endpoint, network route, TLS requirements, account permissions, and a supported client/driver with the SAP administrator. Store any approved credentials outside source control. Keep local SQLite available as a development fallback until an integration is verified.
