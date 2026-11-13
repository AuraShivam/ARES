# Predictive model evaluation

ARES exposes explicit out-of-time evaluation for the shipment-delay and material-demand models. A run saves its model version, date split, sample counts, data fingerprint, parameters, metrics, duration, and requesting account. Evaluation reads operational data and writes only the evaluation-run record; it does not revise shipments, inventory, predictions, or response workflows.

## Run an evaluation

Apply the database migrations first, then run either model from `backend/`:

```sh
python manage.py migrate
python manage.py evaluate_predictive_models --model all
python manage.py evaluate_predictive_models --model shipment_delay --as-of-date 2026-10-31
```

`--as-of-date` must be a date no later than today. It makes historical evaluations repeatable and excludes records whose labels or movements were not yet known on that date. Each command invocation creates a new persisted run, including when the result is `insufficient_data` or `failed`.

Authenticated API clients can create and inspect the same runs:

```http
POST /api/models/evaluations/
Content-Type: application/json

{"model": "shipment_delay"}
```

The model is `shipment_delay` or `material_demand`; `as_of_date` is optional and uses `YYYY-MM-DD`. The POST endpoint is limited to two runs per user per hour. `GET /api/models/evaluations/` returns the latest 50 records and accepts optional `?model=shipment_delay` and `?status=completed` filters. `GET /api/models/evaluations/<uuid>/` returns one record. All routes require authentication. Evaluation metrics are visible to authenticated ARES users because the operational records and reports are shared across the application.

Statuses are `completed`, `insufficient_data`, or `failed` after processing. An insufficient-data run includes the sample counts and threshold that prevented a benchmark. A failed run contains a safe error message; details remain in the backend log. An empty result is not treated as evidence of model quality.

## Shipment-delay backtest

- The target is whether a verified shipment's actual delivery date was later than its original promised ETA.
- Only approver-verified, delivered shipments with consistent order, ETA, and actual dates known by the selected as-of date are eligible. The verification timestamp is used to decide whether a label was available at a historical cutoff.
- Records are split chronologically at a purchase-order date boundary near 80% of distinct order dates. A training outcome is included only if both its actual delivery and its verification happened before the holdout cutoff. Supplier-history features use only outcomes delivered and verified before each order date.
- Training needs at least 40 records and 10 examples of each outcome. The holdout needs at least five late and five on-time outcomes. Otherwise no classifier-quality metrics are published.
- The current logistic-regression classifier is compared with training-set late prevalence and a point-in-time supplier late-rate baseline. Reports include confusion counts, accuracy, balanced accuracy, precision, recall, F1, ROC AUC when both classes are present, Brier score, log loss, five reliability bins, expected calibration error, and Brier improvement over each baseline.
- The conditional late-duration regressor is compared with the training-set median delay. Its tree-derived 20th–80th percentile range is reported with observed holdout coverage; these ranges are not calibrated intervals.

The probability diagnostics describe the selected holdout only. ARES does not fit a probability-calibration transform, and successful evaluation does not independently validate generalization to a new supplier mix, carrier, market, or time period.

## Material-demand backtest

- The final 90 days ending on `as_of_date` are reserved as an out-of-time holdout. Each per-material model is trained only on issue movements that occurred and were recorded in ARES by the day before that window, using up to 180 prior business days.
- A material needs at least 60 calendar days of training history and 10 distinct issue dates. At least three eligible materials are required before the aggregate run is marked complete.
- The model's cumulative demand totals at 7, 30, and 90 days are compared with a weekly seasonal-naive baseline that repeats the final seven training-day quantities.
- Each horizon reports material count, actual and forecast units, MAE and RMSE per material, WAPE, mean bias, and MAE improvement over the baseline. If total actual consumption is zero, WAPE is `null` because its denominator is zero.

Days without a dated issue are treated as zero demand. Backfilled movements recorded after the training cutoff are excluded from model training even when their business date is earlier; the data fingerprint includes record timestamps. Incomplete or unrepresentative movement history can make the model and the baseline look better or worse than real consumption. These metrics are historical measurements, not a guarantee of future accuracy or a calibrated confidence score.

## Reproducibility and interpretation

The `data_fingerprint` is a SHA-256 hash of the sorted data values used for that model's evaluation; the raw rows are not copied into the run. Model random seeds and split rules are fixed. Re-running the same model version against the same fingerprint and software dependencies should reproduce the same metrics. If model behavior or evaluation rules change, update the corresponding model/evaluation version before comparing new runs.

Use a run's `parameters`, `metrics.readiness`, holdout dates, and fingerprint when reviewing results. Compare model metrics with the included baseline before considering deployment changes. The evaluation endpoint is not a training-label editor, does not change live prediction behavior, and does not automate purchasing or response actions. The dashboard's **AI control center → Model evaluation** tab can start either evaluation, view recent persisted runs, and inspect model-versus-baseline metrics. Runs remain subject to the two-per-user-per-hour API throttle and the same data-coverage requirements.
