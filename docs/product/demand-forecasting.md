# Demand forecasting and inventory planning

ARES exposes an advisory demand forecast at `GET /api/inventory/forecast/` and in the dashboard's **Demand planning** page. It returns 7-, 30-, and 90-day demand totals for each material when the dated issue history meets the minimum coverage requirements.

## Data requirements

The forecast uses `InventoryMovement` rows of type `issue` and their `occurred_at` business date. An issue is stored as a negative `quantity_delta`; ARES forecasts its absolute consumed quantity. A current inventory balance is not a demand observation.

Use the CSV import screen to load historical movement records. Import a `Dated inventory movements` template with a stable `source_key`, existing `material_sku` and `warehouse_code`, `movement_type`, signed `quantity_delta`, and `occurred_at` in `YYYY-MM-DD` format. Historical movement imports do not change current on-hand balances. Receipts are retained as history but are not counted as consumption. Link a receipt to its `purchase_order_number` when possible; after three linked orders, ARES uses the average of up to the six most recent actual receipt lead times for that material's preferred supplier. Otherwise it uses the supplier profile lead time, or a 14-day planning default if no preferred supplier is configured. Open approved, in-transit, and delayed purchase orders contribute to projected supply when they have an expected date.

ARES requires at least 60 calendar days of issue history and 10 distinct issue dates for a material before showing an ML forecast. If there is not enough history, forecasts, stockout dates, safety stock, and reorder quantities are `null`, with a specific explanation in the API and dashboard. The seeded demo does not invent historical movement observations.

## Model and outputs

The current per-material scikit-learn random-forest regressor uses daily issue quantities, recent lags, rolling demand averages, variability, and day of week. It generates the next 90 days recursively and reports the totals for each supported horizon. The model is fit from the most recent 180 days of available movement history.

For each material the response includes on-hand quantity, reorder point, supplier lead time, forecasted demand, projected stockout date, suggested reorder amount, safety stock estimate, a possible-idle-stock signal, history coverage, and a human-readable recommendation. Open purchase orders reduce the suggested reorder quantity and are included in the stockout projection. A linked open disruption affecting the preferred supplier adds an explicit review note; ARES does not create purchase orders or execute procurement actions.

Safety stock uses `1.65 × daily-demand standard deviation × √lead time` (an approximate 95% service buffer under a normal-demand assumption). Suggested order quantity covers forecast lead-time demand plus that buffer, less current on-hand stock and dated open inbound orders. The report identifies whether lead time came from linked receipt history, the supplier profile, or the 14-day planning default.

`model_confidence` describes data coverage only. It is not a calibrated probability that the forecast is correct. The forecasts assume the imported issue history is complete and representative; missing usage records, changing production plans, seasonality beyond the modeled weekday pattern, supplier allocation, and unrecorded receipts can materially change results. Possible idle stock means no issue movement is recorded for 90 days after at least 90 days of history; it is a review cue, not a determination of obsolescence.

## API

- `GET /api/inventory/forecast/` returns all material forecasts, the supported horizons, the as-of date, readiness counts, model method, and limitations. The endpoint requires an authenticated ARES account.
- `GET /api/imports/templates/` lists the dated-movement CSV schema.
- `GET /api/inventory-movements/` includes both the business event date (`occurred_at`) and the time ARES recorded the row (`created_at`).

The forecast is recomputed from current PostgreSQL records on request. Results are advisory; review source coverage and the corresponding material/stock records before acting.
