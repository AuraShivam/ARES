"""Chronological, reproducible evaluation for ARES advisory prediction models."""

import hashlib
import json
import logging
import math
import time
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
from django.utils import timezone
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline

from .demand_forecast import (
    LOOKBACK_DAYS,
    MIN_HISTORY_DAYS,
    MIN_ISSUE_DAYS,
    _fit_and_forecast,
    _series_for_material,
)
from .models import InventoryMovement, PredictiveEvaluationRun, Shipment
from .predictive_risk import (
    FEATURE_COLUMNS,
    MIN_LATE_ROWS_FOR_DURATION,
    MIN_ROWS_PER_CLASS,
    MIN_TRAINING_ROWS,
    MODEL_VERSION as SHIPMENT_MODEL_VERSION,
    _conditional_delay,
    _delay_days,
    _features_for,
    _fit_delay_regressor,
    _order_date,
    _preprocessor,
    _verified_deliveries,
)


LOGGER = logging.getLogger("ares.models")
DEMAND_MODEL_VERSION = "ARES material demand forecast v1"
EVALUATION_VERSION = "ARES chronological evaluation v1"
SHIPMENT_TRAIN_FRACTION = 0.8
MIN_HOLDOUT_ROWS_PER_CLASS = 5
DEMAND_HOLDOUT_DAYS = 90
MIN_DEMAND_MATERIALS = 3
DEMAND_HORIZONS = (7, 30, 90)


def _fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _round(value, digits=4):
    return round(float(value), digits)


def _binary_metrics(labels, probabilities):
    """Return discrimination and calibration diagnostics without hiding small samples."""
    y = np.asarray(labels, dtype=int)
    probabilities = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    predicted = (probabilities >= 0.5).astype(int)
    positives = int(np.sum(y == 1))
    negatives = int(np.sum(y == 0))
    true_positive = int(np.sum((y == 1) & (predicted == 1)))
    true_negative = int(np.sum((y == 0) & (predicted == 0)))
    false_positive = int(np.sum((y == 0) & (predicted == 1)))
    false_negative = int(np.sum((y == 1) & (predicted == 0)))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / positives if positives else None
    specificity = true_negative / negatives if negatives else None
    f1 = 2 * precision * recall / (precision + recall) if recall is not None and precision + recall else 0.0

    bins = []
    ece = 0.0
    for index in range(5):
        lower, upper = index / 5, (index + 1) / 5
        mask = (probabilities >= lower) & ((probabilities < upper) if index < 4 else (probabilities <= upper))
        count = int(mask.sum())
        if not count:
            continue
        mean_predicted = float(probabilities[mask].mean())
        observed = float(y[mask].mean())
        ece += count / len(y) * abs(mean_predicted - observed)
        bins.append({
            "lower_bound": lower,
            "upper_bound": upper,
            "count": count,
            "mean_predicted_probability": _round(mean_predicted),
            "observed_late_rate": _round(observed),
        })

    return {
        "sample_count": int(len(y)),
        "late_count": positives,
        "on_time_count": negatives,
        "accuracy": _round(float(np.mean(predicted == y))),
        "balanced_accuracy": _round((recall + specificity) / 2) if recall is not None and specificity is not None else None,
        "precision": _round(precision),
        "recall": _round(recall) if recall is not None else None,
        "f1": _round(f1),
        "roc_auc": _round(roc_auc_score(y, probabilities)) if len(np.unique(y)) == 2 else None,
        "brier_score": _round(float(np.mean((probabilities - y) ** 2))),
        "log_loss": _round(float(-np.mean(y * np.log(probabilities) + (1 - y) * np.log(1 - probabilities)))),
        "expected_calibration_error": _round(ece),
        "calibration_bins": bins,
        "confusion_matrix": {
            "true_on_time": true_negative,
            "false_late_alarm": false_positive,
            "missed_late": false_negative,
            "correctly_predicted_late": true_positive,
        },
    }


def _relative_improvement(baseline, model):
    return _round((baseline - model) / baseline * 100) if baseline > 0 else None


def _shipment_evaluation(as_of_date):
    deliveries = []
    for shipment in _verified_deliveries():
        order_date = _order_date(shipment)
        verified_date = timezone.localtime(shipment.delivery_outcome_verified_at).date()
        if (
            verified_date > as_of_date
            or shipment.actual_delivery_date > as_of_date
            or shipment.eta > as_of_date
            or shipment.eta < order_date
            or shipment.actual_delivery_date < order_date
        ):
            continue
        deliveries.append(shipment)

    deliveries.sort(key=lambda item: (_order_date(item), item.actual_delivery_date, item.reference, str(item.pk)))
    feature_rows = {item.pk: _features_for(item, deliveries) for item in deliveries}
    fingerprint_rows = [{
        "id": str(item.pk),
        "supplier_id": str(item.purchase_order.supplier_id),
        "order_date": _order_date(item).isoformat(),
        "eta": item.eta.isoformat(),
        "actual_delivery_date": item.actual_delivery_date.isoformat(),
        "verified_at": item.delivery_outcome_verified_at.isoformat(),
        "late": item.actual_delivery_date > item.eta,
        "features": feature_rows[item.pk],
    } for item in deliveries]
    parameters = {
        "evaluation_version": EVALUATION_VERSION,
        "split": "80% chronological order-date boundary; training labels must be verified before the first holdout order date",
        "training_fraction_target": SHIPMENT_TRAIN_FRACTION,
        "minimum_training_rows": MIN_TRAINING_ROWS,
        "minimum_training_rows_per_class": MIN_ROWS_PER_CLASS,
        "minimum_holdout_rows_per_class": MIN_HOLDOUT_ROWS_PER_CLASS,
        "classifier": "class-weighted logistic regression using the current shipment feature pipeline",
        "baselines": ["training-set late prevalence", "point-in-time supplier late rate with prevalence fallback"],
        "calibration": "Brier score, log loss, five probability bins, and expected calibration error; no post-hoc calibration transform is fitted",
        "duration_interval": "random-forest tree 20th-80th percentile; interval coverage is measured on late holdout rows",
    }
    data_fingerprint = _fingerprint({"model": SHIPMENT_MODEL_VERSION, "rows": fingerprint_rows})

    if not deliveries:
        return {
            "status": "insufficient_data", "sample_count": 0, "holdout_start_date": None,
            "holdout_end_date": as_of_date, "data_fingerprint": data_fingerprint,
            "parameters": parameters,
            "metrics": {"readiness": {"reason": "No consistent, approver-verified delivered shipments were available by the selected as-of date."}},
        }

    order_dates = sorted({_order_date(item) for item in deliveries})
    if len(order_dates) < 2:
        cutoff = None
        training_shipments, holdout_shipments = [], []
    else:
        split_index = max(1, min(len(order_dates) - 1, math.floor(len(order_dates) * SHIPMENT_TRAIN_FRACTION)))
        cutoff = order_dates[split_index]
        training_shipments = [
            item for item in deliveries
            if _order_date(item) < cutoff
            and item.actual_delivery_date < cutoff
            and timezone.localtime(item.delivery_outcome_verified_at).date() < cutoff
        ]
        holdout_shipments = [item for item in deliveries if _order_date(item) >= cutoff]

    training_rows = [{
        "shipment": item,
        "features": feature_rows[item.pk],
        "late": item.actual_delivery_date > item.eta,
        "delay_days": _delay_days(item),
    } for item in training_shipments]
    holdout_rows = [{
        "shipment": item,
        "features": feature_rows[item.pk],
        "late": item.actual_delivery_date > item.eta,
        "delay_days": _delay_days(item),
    } for item in holdout_shipments]
    training_labels = [int(row["late"]) for row in training_rows]
    holdout_labels = [int(row["late"]) for row in holdout_rows]
    training_late = sum(training_labels)
    training_on_time = len(training_labels) - training_late
    holdout_late = sum(holdout_labels)
    holdout_on_time = len(holdout_labels) - holdout_late
    readiness = {
        "verified_shipments_by_as_of_date": len(deliveries),
        "training_rows_with_labels_available_at_cutoff": len(training_rows),
        "holdout_rows": len(holdout_rows),
        "training_late_count": training_late,
        "training_on_time_count": training_on_time,
        "holdout_late_count": holdout_late,
        "holdout_on_time_count": holdout_on_time,
        "cutoff_date": cutoff.isoformat() if cutoff else None,
    }
    if (
        len(training_rows) < MIN_TRAINING_ROWS
        or min(training_late, training_on_time) < MIN_ROWS_PER_CLASS
        or min(holdout_late, holdout_on_time) < MIN_HOLDOUT_ROWS_PER_CLASS
    ):
        reasons = []
        if len(training_rows) < MIN_TRAINING_ROWS:
            reasons.append(f"need at least {MIN_TRAINING_ROWS} training shipments whose labels were known before the holdout cutoff")
        if min(training_late, training_on_time) < MIN_ROWS_PER_CLASS:
            reasons.append(f"training data needs at least {MIN_ROWS_PER_CLASS} late and {MIN_ROWS_PER_CLASS} on-time examples")
        if min(holdout_late, holdout_on_time) < MIN_HOLDOUT_ROWS_PER_CLASS:
            reasons.append(f"holdout needs at least {MIN_HOLDOUT_ROWS_PER_CLASS} late and {MIN_HOLDOUT_ROWS_PER_CLASS} on-time examples")
        return {
            "status": "insufficient_data", "sample_count": len(holdout_rows),
            "holdout_start_date": cutoff, "holdout_end_date": as_of_date,
            "data_fingerprint": data_fingerprint, "parameters": parameters,
            "metrics": {"readiness": {**readiness, "reason": "; ".join(reasons)}},
        }

    prevalence = float(np.mean(training_labels))
    classifier = Pipeline([
        ("features", _preprocessor()),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)),
    ])
    training_frame = pd.DataFrame([row["features"] for row in training_rows], columns=FEATURE_COLUMNS)
    holdout_frame = pd.DataFrame([row["features"] for row in holdout_rows], columns=FEATURE_COLUMNS)
    classifier.fit(training_frame, training_labels)
    model_probabilities = classifier.predict_proba(holdout_frame)[:, list(classifier.classes_).index(1)]
    global_probabilities = np.full(len(holdout_rows), prevalence, dtype=float)
    supplier_probabilities = np.asarray([
        row["features"]["supplier_prior_late_rate"]
        if row["features"]["supplier_prior_delivery_count"] > 0
        else prevalence
        for row in holdout_rows
    ], dtype=float)

    model_metrics = _binary_metrics(holdout_labels, model_probabilities)
    global_metrics = _binary_metrics(holdout_labels, global_probabilities)
    supplier_metrics = _binary_metrics(holdout_labels, supplier_probabilities)
    delay_model = _fit_delay_regressor(training_rows, [row["late"] for row in training_rows])
    duration = {"available": False, "reason": f"At least {MIN_LATE_ROWS_FOR_DURATION} late training outcomes are required."}
    late_holdout = [row for row in holdout_rows if row["late"]]
    if delay_model and late_holdout:
        estimates = [_conditional_delay(delay_model, row["features"]) for row in late_holdout]
        actual = np.asarray([row["delay_days"] for row in late_holdout], dtype=float)
        predicted = np.asarray([item["expected_delay_days"] for item in estimates], dtype=float)
        intervals = [item["delay_range_days"] for item in estimates]
        median_baseline = float(np.median([row["delay_days"] for row in training_rows if row["late"]]))
        baseline_mae = float(np.mean(np.abs(actual - median_baseline)))
        coverage = float(np.mean([
            low <= observed <= high
            for (low, high), observed in zip(intervals, actual)
        ]))
        duration = {
            "available": True,
            "sample_count": len(actual),
            "mae_days": _round(float(np.mean(np.abs(actual - predicted))), 2),
            "rmse_days": _round(float(np.sqrt(np.mean((actual - predicted) ** 2))), 2),
            "training_median_baseline_mae_days": _round(baseline_mae, 2),
            "mae_improvement_percent_vs_training_median": _relative_improvement(
                baseline_mae, float(np.mean(np.abs(actual - predicted)))
            ),
            "tree_interval_nominal_coverage_percent": 60,
            "tree_interval_observed_coverage_percent": _round(coverage * 100, 1),
            "mean_tree_interval_width_days": _round(float(np.mean([high - low for low, high in intervals])), 2),
            "interval_warning": "Tree percentile ranges are not calibrated prediction intervals; coverage is empirical on this holdout only.",
        }

    global_brier = global_metrics["brier_score"]
    supplier_brier = supplier_metrics["brier_score"]
    model_brier = model_metrics["brier_score"]
    metrics = {
        "readiness": readiness,
        "classification": {
            "model": model_metrics,
            "baselines": {
                "training_late_prevalence": global_metrics,
                "point_in_time_supplier_rate": supplier_metrics,
            },
            "brier_improvement_percent_vs_training_prevalence": _relative_improvement(global_brier, model_brier),
            "brier_improvement_percent_vs_supplier_rate": _relative_improvement(supplier_brier, model_brier),
            "probability_interpretation": "Brier, log loss, and reliability bins describe this chronological holdout; the model probabilities have not been independently calibrated.",
        },
        "delay_duration": duration,
    }
    return {
        "status": "completed", "sample_count": len(holdout_rows),
        "holdout_start_date": cutoff, "holdout_end_date": as_of_date,
        "data_fingerprint": data_fingerprint, "parameters": parameters, "metrics": metrics,
    }


def _regression_metrics(actual_by_material, forecast_by_material):
    errors = np.asarray(forecast_by_material, dtype=float) - np.asarray(actual_by_material, dtype=float)
    actual = np.asarray(actual_by_material, dtype=float)
    forecast = np.asarray(forecast_by_material, dtype=float)
    actual_total = float(actual.sum())
    return {
        "material_count": int(len(actual)),
        "actual_total_units": _round(actual_total, 2),
        "forecast_total_units": _round(float(forecast.sum()), 2),
        "mae_units_per_material": _round(float(np.mean(np.abs(errors))), 2) if len(errors) else None,
        "rmse_units_per_material": _round(float(np.sqrt(np.mean(errors ** 2))), 2) if len(errors) else None,
        "wape_percent": _round(float(np.abs(errors).sum() / actual_total * 100), 2) if actual_total > 0 else None,
        "mean_bias_units_per_material": _round(float(errors.mean()), 2) if len(errors) else None,
    }


def _demand_evaluation(as_of_date):
    cutoff = as_of_date - timedelta(days=DEMAND_HOLDOUT_DAYS)
    # Keep 180 training days before the cutoff plus the 90-day out-of-time target window.
    history_start = cutoff - timedelta(days=LOOKBACK_DAYS - 1)
    movement_rows = list(
        InventoryMovement.objects.filter(
            movement_type="issue",
            occurred_at__gte=history_start,
            occurred_at__lte=as_of_date,
        )
        .values("id", "inventory__material_id", "occurred_at", "quantity_delta", "created_at")
        .order_by("inventory__material_id", "occurred_at", "created_at", "id")
    )
    histories = defaultdict(list)
    training_daily = defaultdict(float)
    holdout_daily = defaultdict(float)
    canonical_movements = []
    for row in movement_rows:
        material_id = row["inventory__material_id"]
        quantity = abs(float(row["quantity_delta"] or 0))
        recorded_at = timezone.localtime(row["created_at"])
        if recorded_at.date() > as_of_date:
            continue
        canonical_movements.append({
            "id": str(row["id"]),
            "material_id": str(material_id),
            "occurred_at": row["occurred_at"].isoformat(),
            "recorded_at": recorded_at.isoformat(),
            "quantity": format(quantity, ".8f"),
        })
        if row["occurred_at"] <= cutoff and recorded_at.date() <= cutoff:
            training_daily[(material_id, row["occurred_at"])] += quantity
        elif cutoff < row["occurred_at"] <= as_of_date:
            holdout_daily[(material_id, row["occurred_at"])] += quantity

    for (material_id, day), quantity in sorted(training_daily.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        histories[material_id].append({"occurred_at": day, "quantity": quantity})

    parameters = {
        "evaluation_version": EVALUATION_VERSION,
        "split": "fixed 90-day holdout; training issues must have occurred and been recorded in ARES by the cutoff",
        "training_window_days": LOOKBACK_DAYS,
        "holdout_days": DEMAND_HOLDOUT_DAYS,
        "minimum_training_coverage_days": MIN_HISTORY_DAYS,
        "minimum_distinct_issue_dates": MIN_ISSUE_DAYS,
        "minimum_materials_for_aggregate_metrics": MIN_DEMAND_MATERIALS,
        "model": DEMAND_MODEL_VERSION,
        "baseline": "weekly seasonal naive: repeat the final seven observed daily quantities",
        "horizons_days": list(DEMAND_HORIZONS),
    }
    fingerprint = _fingerprint({"model": DEMAND_MODEL_VERSION, "movements": canonical_movements})
    material_results = []
    for material_id, rows in histories.items():
        training_history = [row for row in rows if row["occurred_at"] <= cutoff]
        daily, start, issue_days = _series_for_material(training_history, cutoff)
        coverage_days = (cutoff - start).days + 1 if start else 0
        if daily is None or coverage_days < MIN_HISTORY_DAYS or issue_days < MIN_ISSUE_DAYS:
            continue
        forecast = _fit_and_forecast(daily)
        if forecast is None:
            continue
        values = daily.to_numpy(dtype=float)
        weekly_baseline = [float(values[-7 + index % 7]) for index in range(DEMAND_HOLDOUT_DAYS)]
        actual_values = [
            holdout_daily[(material_id, cutoff + timedelta(days=index))]
            for index in range(1, DEMAND_HOLDOUT_DAYS + 1)
        ]
        material_results.append({
            "model": [float(value) for value in forecast[:DEMAND_HOLDOUT_DAYS]],
            "baseline": weekly_baseline,
            "actual": actual_values,
        })

    metrics = {"readiness": {
        "materials_with_eligible_training_history": len(material_results),
        "issue_movement_rows_available_by_as_of_date": len(canonical_movements),
        "training_cutoff_date": cutoff.isoformat(),
    }}
    if len(material_results) < MIN_DEMAND_MATERIALS:
        metrics["readiness"]["reason"] = (
            f"Need at least {MIN_DEMAND_MATERIALS} materials with {MIN_HISTORY_DAYS} training days and "
            f"{MIN_ISSUE_DAYS} distinct dated issue days before the 90-day holdout."
        )
        return {
            "status": "insufficient_data", "sample_count": len(material_results),
            "holdout_start_date": cutoff + timedelta(days=1), "holdout_end_date": as_of_date,
            "data_fingerprint": fingerprint, "parameters": parameters, "metrics": metrics,
        }

    horizons = {}
    for horizon in DEMAND_HORIZONS:
        model_actual, model_forecast, baseline_forecast = [], [], []
        for result in material_results:
            model_actual.append(sum(result["actual"][:horizon]))
            model_forecast.append(sum(result["model"][:horizon]))
            baseline_forecast.append(sum(result["baseline"][:horizon]))
        model_metrics = _regression_metrics(model_actual, model_forecast)
        baseline_metrics = _regression_metrics(model_actual, baseline_forecast)
        horizons[str(horizon)] = {
            "model": model_metrics,
            "baseline": baseline_metrics,
            "mae_improvement_percent_vs_weekly_seasonal_naive": _relative_improvement(
                baseline_metrics["mae_units_per_material"], model_metrics["mae_units_per_material"]
            ),
        }
    metrics.update({
        "horizons": horizons,
        "forecast_interpretation": "Metrics compare material-level cumulative demand over each horizon. They are out-of-time measurements for this dataset, not a guarantee of future accuracy.",
        "coverage_limit": "Days without a recorded issue are treated as zero consumption; incomplete movement imports can bias both model and baseline metrics.",
    })
    return {
        "status": "completed", "sample_count": len(material_results),
        "holdout_start_date": cutoff + timedelta(days=1), "holdout_end_date": as_of_date,
        "data_fingerprint": fingerprint, "parameters": parameters, "metrics": metrics,
    }


def run_predictive_evaluation(model_type, as_of_date=None, requested_by=None):
    """Create and persist an evaluation, including explicit insufficient/failed states."""
    if model_type not in {"shipment_delay", "material_demand"}:
        raise ValueError("model_type must be shipment_delay or material_demand")
    as_of_date = as_of_date or timezone.localdate()
    if as_of_date > timezone.localdate():
        raise ValueError("as_of_date cannot be in the future")
    model_version = SHIPMENT_MODEL_VERSION if model_type == "shipment_delay" else DEMAND_MODEL_VERSION
    run = PredictiveEvaluationRun.objects.create(
        requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
        model_type=model_type,
        status="running",
        model_version=model_version,
        as_of_date=as_of_date,
    )
    started = time.monotonic()
    try:
        result = _shipment_evaluation(as_of_date) if model_type == "shipment_delay" else _demand_evaluation(as_of_date)
        run.status = result["status"]
        run.holdout_start_date = result["holdout_start_date"]
        run.holdout_end_date = result["holdout_end_date"]
        run.sample_count = result["sample_count"]
        run.data_fingerprint = result["data_fingerprint"]
        run.parameters = result["parameters"]
        run.metrics = result["metrics"]
    except Exception:
        LOGGER.exception("Predictive evaluation failed (run_id=%s, model_type=%s)", run.pk, model_type)
        run.status = "failed"
        run.error_code = "evaluation_failed"
        run.error_message = "The evaluation failed. Check the application log for details; no operational records were changed."
    run.duration_ms = min(2**32 - 1, int((time.monotonic() - started) * 1000))
    run.save(update_fields=[
        "status", "holdout_start_date", "holdout_end_date", "sample_count", "data_fingerprint",
        "parameters", "metrics", "error_code", "error_message", "duration_ms", "updated_at",
    ])
    return run
