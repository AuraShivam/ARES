# ARES risk intelligence

ARES has two distinct risk capabilities. `POST /api/risk/assess/` remains a transparent, deterministic disruption assessment. A separate shipment-delay model trains on demand from approver-verified delivery outcomes and only returns predictions when the stored history meets its minimum data requirements. The disruption rules are implemented in `backend/supply_chain/risk.py`; the shipment predictor is in `backend/supply_chain/predictive_risk.py`.

## Evidence used

The assessment starts with disruption severity and reported confidence, then gathers records linked by the affected supplier and/or shipment:

- Supplier risk profile, status, and lead time.
- Shipment risk score, delivery status, and overdue ETA.
- Open purchase orders and the subset already marked delayed.
- Linked materials' criticality and total on-hand quantity compared with combined reorder points.
- Affected-region matches against supplier, shipment route, and warehouse regions.
- Imported source timestamps on linked suppliers, open purchase orders, materials, and inventory balances. Timestamps older than 90 days are flagged as stale.
- Imported disruptions and linked shipments include their source timestamps in freshness evidence when the record has a named source.

The response also reports missing links, missing inventory coverage, stale sources, and records with no source timestamp. Missing inventory and stale data add bounded uncertainty points; gaps are visible even when they do not change the score. Missing source timestamps are surfaced but do not by themselves add points.

Every call to `POST /api/risk/assess/` stores an assessment snapshot with its explanation and trigger. A newly created or materially updated GDACS source event also reassesses its linked disruption in the same database transaction. `GET /api/risk/assessments/` lists snapshots; add `?disruption_id=<uuid>` to filter to one disruption.

## Rule weights

| Signal | Contribution |
| --- | --- |
| Severity | Low 15, medium 35, high 60, critical 80 base points |
| Supplier risk profile | 15% of supplier risk score, rounded |
| Supplier status | Watch +6; blocked +14 |
| Supplier lead time | +2 for each full week above 21 days, capped at +6 |
| Shipment risk score | 12% of shipment risk score, rounded; no shipment-risk points after delivery |
| Shipment status | Delayed or at risk +8 |
| Shipment ETA | Past ETA and not delivered +8 |
| Open purchase orders | +2 per order, capped at +8 |
| Delayed purchase orders | +3 per order, capped at +6 |
| Material criticality | Highest linked material: medium +4, high +8 |
| Inventory at/below reorder | +4 per material, capped at +12 |
| Missing inventory records | +2 per material, capped at +6 |
| Affected-region match | +6 |
| Stale source timestamps | +2 per linked record, capped at +6 |
| Reported confidence | Adds up to 10 points as confidence decreases |

Contributions are summed and capped at 100. Bands are low (0–34), moderate (35–59), high (60–79), and critical (80–100). Recommendations use the same band thresholds and remain advisory; ARES does not execute operational actions.

## Predictive shipment delay and shortage outlook

`GET /api/risk/predictive/` builds the current model from completed shipments with an ETA, an actual delivery date, `delivery_outcome_verified=true`, and delivered status. The API trains a scikit-learn logistic-regression classifier for late-arrival probability and, when enough late examples exist, a random-forest regressor for delay duration. It trains from current database records on request; no model artifact or predictions are seeded in the demo database.

The pilot readiness gate requires at least 40 eligible verified shipments, including at least 10 late and 10 on-time shipments. Delay ranges separately require at least 8 late examples. These are minimum technical gates, not evidence that the model is accurate. The API marks predictions experimental and not independently validated. “Model confidence” is the highest class probability from the classifier; it is not a calibrated guarantee. The explanation lists local logistic-model feature contributions as associations, not causes.

Features include supplier late rate and average delay among verified outcomes known before the purchase-order date, recent supplier performance, order-to-promise window, order quantity, supplier, carrier, route, and promised-arrival month. Set `ordered_at` when importing historical purchase orders so the supplier-history features use the correct point in time. If it is absent, ARES falls back to the purchase order's database creation date.

Import shipment `eta` and `actual_delivery_date` as dates. For training, keep `eta` as the original committed promise; replacing it with a revised forecast changes the late/on-time label. An imported actual date is not trusted automatically. An ARES staff member or `ares_approvers` member must verify the delivered shipment using `POST /api/shipments/<shipment-uuid>/verify-delivery/` with `actual_delivery_date` and evidence notes. Editing a verified shipment's model inputs or its purchase order's supplier/date/quantity clears the verification and requires a new review. Verification is audited.

Delay-related shortage estimates use the recent 30 days of recorded inventory issue movements to estimate days of stock cover. A material needs at least three issue records spanning at least seven observed days and a positive consumption rate. On-hand quantity is aggregated across warehouses because ARES does not yet map shipments to a destination warehouse. The estimate combines classifier late probability with the conditional delay forest distribution and reports the highest per-material exposure; it does not assume materials fail independently. If demand or delay history is insufficient, the API returns a null estimate with an explanation. A projected stockout before the promised arrival is shown separately from shortage risk attributable to a later delay.

Supplier trends compare the late-arrival rate in the most recent 90 days with the preceding 90 days. A direction is shown only when both periods contain at least three verified shipments; a rise means a difference of at least 10 percentage points. This is an observed-history trend, not a causal claim.

The dashboard's **Risk intelligence** page shows shipment predictions, confidence, feature factors, duration ranges, shortage likelihood, supplier trends, and an approver form to verify delivered outcomes. The current demo data has no verified shipment training labels, so it should show the data-readiness message until real outcomes are entered and reviewed. Never present an illustrative probability as a prediction from the current demo data.

## Representative scenario evaluation

From `backend/`, run:

```sh
python manage.py evaluate_risk
```

The command scores fixed examples for a low-impact event, a high-impact event with missing links, a watch-listed supplier with regional order exposure, a critical multi-signal event, and a low-severity event affecting critical material below reorder. It reports whether each result matches its intended risk band. The scenarios make rule changes reviewable and reproducible; they are not a substitute for calibration against confirmed historical incidents or measurement of real-world predictive accuracy.

## Alerts and reassessment

The risk alert threshold defaults to a score of 60 and is set with `ARES_RISK_ALERT_SCORE_THRESHOLD` (valid values 0–100). An alert opens when an assessment meets or exceeds that score. A score below threshold or a resolved disruption clears the active alert. `ARES_RISK_ALERT_COOLDOWN_MINUTES` defaults to 60; repeated assessments for an active alert are deduplicated, and the alert can be generated again after cooldown. A higher risk band generates an immediate escalation. The active alert record tracks its latest assessment, generated-alert count, deduplicated assessments, cooldown suppressions, and whether a notification is due. `GET /api/risk/alerts/` lists alerts; `?status=active` returns the current queue. `GET /api/risk/policy/` returns effective non-secret thresholds.

Phase 5 queues email notifications for alert open, escalation, and clear events. Actual SMTP delivery requires an explicitly enabled and configured email provider; see the [response workflow guide](response-plans.md). The dashboard shows active alerts and the overview count. Chat/push channels and delivery acknowledgment are not implemented.

## Outcome labels and calibration report

Only a staff user or member of `ares_approvers` can inspect, enter, or correct reviewed outcomes. The dashboard's **Risk intelligence** page records a result for an assessed disruption and requires evidence notes. The API accepts `POST /api/risk/outcomes/` with `disruption_id`, `outcome` (`impact` or `no_impact`), and optional `evidence_notes`; `GET /api/risk/outcomes/` lists labels to approvers. The endpoint stores reviewer identity and time, supports corrections by updating the current label, and writes an audit event. Do not label a case unless its outcome has been verified; GDACS event presence alone does not establish material impact on an ARES supply chain.

`GET /api/risk/calibration/` and `python manage.py calibrate_risk` compare each labeled disruption with its latest assessment. They report case counts and observed impact rates by risk band, plus precision and recall at the configured alert threshold. This is a descriptive evaluation only: no labels are seeded, and the report does not train or auto-adjust the rules. ARES should not be described as empirically calibrated until enough representative, verified outcomes have been collected and reviewed.

## Limits

- Inputs are the records currently stored in ARES. GDACS is a global natural-disaster signal, not supplier/carrier telemetry, and does not confirm that a particular ARES facility or route is affected.
- Region matching is a simple normalized text match, not geospatial analysis.
- Order count, stock coverage, and source age are proxies. The rules do not model revenue, substitution time, demand forecasts, or network propagation.
- The shipment model estimates late delivery, not disruption probability or monetary loss. Its probability scores are experimental, not independently calibrated, and depend on enough representative, verified historical outcomes.
- The shortage estimate uses recent issue movements as a demand proxy and a conditional delay distribution; it is not a full demand forecast or multi-echelon inventory simulation.
- Source-event reassessment currently runs for GDACS ingestion. Changes to unrelated supplier, inventory, purchase-order, or shipment records do not automatically fan out into disruption reassessments.
