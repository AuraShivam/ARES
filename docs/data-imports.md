# ARES CSV imports

The dashboard's **CSV imports** section previews and validates an upload before any supply-chain record is written. Import batches and row results are retained as provenance; raw row values are kept in the database for revalidation but are not returned by the import API.

## Supported records

Import in dependency order. Materials may refer to suppliers, inventory refers to materials and warehouses, purchase orders refer to suppliers and materials, and shipments refer to purchase orders. Disruptions can optionally reference a supplier or shipment.

| Type | Required columns | Optional columns | Match key |
| --- | --- | --- | --- |
| Suppliers | `code`, `name` | `country`, `region`, `risk_score`, `lead_time_days`, `status`, `source_key`, `source_updated_at` | `code` |
| Materials | `sku`, `name` | `category`, `unit`, `criticality`, `preferred_supplier_code`, `source_key`, `source_updated_at` | `sku` |
| Warehouses | `code`, `name` | `region`, `country`, `warehouse_type`, `active`, `source_key`, `source_updated_at` | `code` |
| Inventory balances | `material_sku`, `warehouse_code`, `quantity` | `reorder_point`, `unit_cost`, `source_key`, `source_updated_at` | `material_sku` + `warehouse_code` |
| Purchase orders | `number`, `supplier_code`, `material_sku`, `quantity` | `expected_date`, `status`, `currency`, `unit_price`, `source_key`, `source_updated_at` | `number` |
| Shipments | `reference`, `purchase_order_number`, `origin`, `destination` | `carrier`, `eta`, `status`, `risk_score`, `source_key`, `source_updated_at` | `reference` |
| Disruptions | `source_key`, `title`, `severity` | `disruption_type`, `description`, `affected_region`, `status`, `confidence`, `affected_supplier_code`, `shipment_reference`, `source_updated_at` | `source_name` + `source_key` |

Templates can be downloaded from the import dialog. Files must be UTF-8 CSV, at most 5 MB, and contain no more than 2,000 nonblank data rows. Header matching ignores case and normalizes spaces/punctuation to underscores; unsupported, duplicate, or missing required headers are rejected.

Dates use `YYYY-MM-DD`. `source_updated_at` must be a timezone-aware ISO 8601 timestamp. Decimal values use a period as the decimal separator. `active` accepts `true`/`false`, `yes`/`no`, or `1`/`0`. Domain choices such as supplier status, material criticality, purchase-order status, shipment status, and disruption severity are validated against the model. Disruption imports require a stable source key so repeated imports can safely find the same event.

## Duplicate and update behavior

- **Skip existing** is the default. Existing records with valid rows are shown as skipped.
- **Update existing** updates the record matched by its natural key. Purchase-order CSV updates currently support orders with a single line; use the purchase-order API for multi-line orders.
- **Flag duplicates as errors** blocks commit if a match already exists.
- A natural key repeated within the uploaded CSV is an error under every policy.
- Rows with validation errors prevent the whole batch from committing.
- The commit step rechecks current database state and writes all accepted rows in one transaction. A changed/conflicting preview must be uploaded and reviewed again.
- On an update, blank optional cells preserve existing values; omitted columns also preserve values. On a new record, blank optional cells use the model's default or empty value. `source_name` records the latest import source, and `source_key` defaults to the natural key when no source key is provided.
- Updating an existing inventory balance creates an inventory adjustment movement when the quantity changes. The initial balance created for a new inventory record does not create a movement.
- Shipment rows resolve their purchase-order number to an existing order. Disruption rows match on the selected source name and source key; optional supplier/shipment references must already exist.

## GDACS live feed

ARES includes a global GDACS recent-disaster feed connector. The public feed is refreshed by GDACS about every six minutes, so the connector enforces a six-minute minimum polling interval. It defaults to importing Orange and Red alerts; set `ARES_GDACS_MIN_ALERT_LEVEL=green` to include Green events. No API credential is required. GDACS requests source attribution, which ARES records on imported disruptions and displays in their descriptions. Feed entries age out of the rolling 24-hour source window; that only updates source-event history and never resolves an ARES disruption.

From `backend/`, run one sync with `python manage.py sync_gdacs_alerts`, or keep polling with `python manage.py sync_gdacs_alerts --watch`. Configure `ARES_GDACS_POLL_INTERVAL_SECONDS` (minimum 360) and `ARES_GDACS_MIN_ALERT_LEVEL` in the backend environment. The authenticated `GET /api/feeds/status/` endpoint reports the last attempt, last success, freshness, counts, errors, and current source events.

## API

- `GET /api/imports/templates/` describes headers and limits.
- `GET /api/imports/` lists the latest 100 batches.
- `POST /api/imports/preview/` takes multipart fields `entity_type`, `source_name`, `duplicate_policy`, and `file`; it returns row-level actions/errors and creates a preview batch.
- `GET /api/imports/<batch-uuid>/` returns that batch and its row results.
- `POST /api/imports/<batch-uuid>/commit/` revalidates and commits a clean preview. Stale or invalid previews return HTTP 409.

Import row results intentionally exclude stored raw CSV values. Import routes require an authenticated account. Production hosting, secret management, and security hardening are still required before exposing the service publicly; see [security and quality](security-quality.md).
