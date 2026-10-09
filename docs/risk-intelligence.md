# ARES risk intelligence

ARES currently uses deterministic rules rather than a trained or hosted AI model. `POST /api/risk/assess/` returns a 0–100 score, a risk band, a point-by-point explanation, linked evidence coverage, data gaps, and a human-reviewed recommendation. The rules are implemented in `backend/supply_chain/risk.py`.

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

Only a staff user or member of `ares_approvers` can enter a reviewed outcome. Submit `POST /api/risk/outcomes/` with `disruption_id`, `outcome` (`impact` or `no_impact`), and optional `evidence_notes`. The endpoint stores the reviewer identity and time, supports corrections by updating the current label, and writes an audit event. Do not label a case unless its outcome has been verified; GDACS event presence alone does not establish material impact on an ARES supply chain.

`GET /api/risk/calibration/` and `python manage.py calibrate_risk` compare each labeled disruption with its latest assessment. They report case counts and observed impact rates by risk band, plus precision and recall at the configured alert threshold. This is a descriptive evaluation only: no labels are seeded, and the report does not train or auto-adjust the rules. ARES should not be described as empirically calibrated until enough representative, verified outcomes have been collected and reviewed.

## Limits

- Inputs are the records currently stored in ARES. GDACS is a global natural-disaster signal, not supplier/carrier telemetry, and does not confirm that a particular ARES facility or route is affected.
- Region matching is a simple normalized text match, not geospatial analysis.
- Order count, stock coverage, and source age are proxies. The rules do not model revenue, substitution time, demand forecasts, or network propagation.
- No trained AI model, probability of disruption, or empirically calibrated loss estimate is claimed.
- Source-event reassessment currently runs for GDACS ingestion. Changes to unrelated supplier, inventory, purchase-order, or shipment records do not automatically fan out into disruption reassessments.
