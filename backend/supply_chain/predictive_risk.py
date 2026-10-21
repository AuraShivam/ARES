"""Shipment delay predictions trained only from approver-verified outcomes."""

from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
from django.utils import timezone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .models import Inventory, InventoryMovement, Shipment


MODEL_VERSION = "ARES shipment delay model v1"
MIN_TRAINING_ROWS = 40
MIN_ROWS_PER_CLASS = 10
MIN_LATE_ROWS_FOR_DURATION = 8
DEMAND_LOOKBACK_DAYS = 30
TREND_WINDOW_DAYS = 90
MIN_TREND_ROWS_PER_WINDOW = 3

NUMERIC_FEATURES = [
    "supplier_prior_late_rate",
    "supplier_prior_average_delay_days",
    "supplier_prior_delivery_count",
    "supplier_recent_late_rate",
    "supplier_recent_delivery_count",
    "commitment_window_days",
    "order_quantity",
]
CATEGORICAL_FEATURES = [
    "supplier_code",
    "carrier",
    "origin",
    "destination",
    "eta_month",
]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

FEATURE_LABELS = {
    "supplier_prior_late_rate": "Supplier's prior late-delivery rate",
    "supplier_prior_average_delay_days": "Supplier's prior average delay",
    "supplier_prior_delivery_count": "Supplier's prior verified delivery count",
    "supplier_recent_late_rate": "Supplier's recent late-delivery rate",
    "supplier_recent_delivery_count": "Supplier's recent verified delivery count",
    "commitment_window_days": "Days from order to promised arrival",
    "order_quantity": "Purchase-order quantity",
    "supplier_code": "Supplier history",
    "carrier": "Carrier history",
    "origin": "Shipment origin",
    "destination": "Shipment destination",
    "eta_month": "Promised arrival month",
}


def _verified_deliveries():
    return list(
        Shipment.objects.filter(
            delivery_outcome_verified=True,
            status="delivered",
            eta__isnull=False,
            actual_delivery_date__isnull=False,
        )
        .select_related("purchase_order", "purchase_order__supplier")
        .prefetch_related("purchase_order__lines")
        .order_by("actual_delivery_date", "eta", "reference")
    )


def _order_date(shipment):
    order = shipment.purchase_order
    return order.ordered_at or (order.created_at.date() if order.created_at else shipment.created_at.date())


def _delay_days(shipment):
    return max(0, (shipment.actual_delivery_date - shipment.eta).days)


def _features_for(shipment, verified_deliveries):
    """Build point-in-time features using only delivery outcomes known at order time."""
    order_date = _order_date(shipment)
    supplier_id = shipment.purchase_order.supplier_id
    prior = [
        item for item in verified_deliveries
        if item.pk != shipment.pk
        and item.purchase_order.supplier_id == supplier_id
        and item.actual_delivery_date < order_date
    ]
    recent_start = order_date - timedelta(days=180)
    recent = [item for item in prior if item.actual_delivery_date >= recent_start]
    prior_late = [item for item in prior if _delay_days(item) > 0]
    recent_late = [item for item in recent if _delay_days(item) > 0]
    eta = shipment.eta
    order = shipment.purchase_order
    lines = list(order.lines.all())
    quantity = sum((line.quantity for line in lines), start=0) if lines else order.quantity

    values = {
        "supplier_prior_late_rate": len(prior_late) / len(prior) if prior else 0.0,
        "supplier_prior_average_delay_days": (
            sum(_delay_days(item) for item in prior_late) / len(prior_late) if prior_late else 0.0
        ),
        "supplier_prior_delivery_count": len(prior),
        "supplier_recent_late_rate": len(recent_late) / len(recent) if recent else 0.0,
        "supplier_recent_delivery_count": len(recent),
        "commitment_window_days": max(0, (eta - order_date).days),
        "order_quantity": float(quantity or 0),
        "supplier_code": shipment.purchase_order.supplier.code or "Unknown",
        "carrier": shipment.carrier or "Unknown",
        "origin": shipment.origin or "Unknown",
        "destination": shipment.destination or "Unknown",
        "eta_month": str(eta.month),
    }
    return values


def _preprocessor():
    return ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ],
        remainder="drop",
    )


def _local_factors(model, features):
    preprocessor = model.named_steps["features"]
    classifier = model.named_steps["classifier"]
    transformed = preprocessor.transform(pd.DataFrame([features], columns=FEATURE_COLUMNS))
    if hasattr(transformed, "toarray"):
        transformed = transformed.toarray()
    names = preprocessor.get_feature_names_out()
    contributions = transformed[0] * classifier.coef_[0]
    factors = []
    for index in np.argsort(np.abs(contributions))[::-1]:
        contribution = float(contributions[index])
        if abs(contribution) < 0.05:
            continue
        model_feature = str(names[index])
        if model_feature.startswith("numeric__"):
            source = model_feature.removeprefix("numeric__")
            feature_name = FEATURE_LABELS[source]
            value = features[source]
            if source.endswith("late_rate"):
                detail = f"{value * 100:.0f}% based on the recorded prior deliveries."
            elif source.endswith("delivery_count"):
                detail = f"{int(value)} prior verified delivery record(s)."
            elif source.endswith("delay_days"):
                detail = f"{value:.1f} average late days in prior verified deliveries."
            elif source == "commitment_window_days":
                detail = f"The order had {int(value)} day(s) between order and promised arrival."
            else:
                detail = f"Recorded order quantity: {value:g}."
        else:
            category_name = model_feature.removeprefix("categorical__")
            source = next((name for name in CATEGORICAL_FEATURES if category_name.startswith(f"{name}_")), None)
            if source is None:
                continue
            feature_name = FEATURE_LABELS[source]
            detail = f"Recorded value: {features[source]}."
        factors.append({
            "factor": feature_name,
            "direction": "raises" if contribution > 0 else "lowers",
            "detail": detail,
            "relative_effect": round(abs(contribution), 3),
        })
        if len(factors) == 5:
            break
    return factors


def _fit_delay_regressor(training_rows, labels):
    late_rows = [row for row, late in zip(training_rows, labels) if late]
    if len(late_rows) < MIN_LATE_ROWS_FOR_DURATION:
        return None
    frame = pd.DataFrame([row["features"] for row in late_rows], columns=FEATURE_COLUMNS)
    delays = [row["delay_days"] for row in late_rows]
    return Pipeline([
        ("features", _preprocessor()),
        ("regressor", RandomForestRegressor(
            n_estimators=120,
            max_depth=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=1,
        )),
    ]).fit(frame, delays)


def _conditional_delay(regressor, features):
    transformed = regressor.named_steps["features"].transform(pd.DataFrame([features], columns=FEATURE_COLUMNS))
    trees = np.asarray([
        tree.predict(transformed)[0]
        for tree in regressor.named_steps["regressor"].estimators_
    ])
    low, median, high = np.quantile(trees, [0.2, 0.5, 0.8])
    return {
        "expected_delay_days": round(max(0.0, float(median)), 1),
        "delay_range_days": [round(max(0.0, float(low)), 1), round(max(0.0, float(high)), 1)],
        "tree_delay_estimates": trees,
    }


def _supplier_trends(deliveries, today):
    by_supplier = defaultdict(list)
    for shipment in deliveries:
        by_supplier[shipment.purchase_order.supplier_id].append(shipment)
    result = []
    for shipments in by_supplier.values():
        supplier = shipments[0].purchase_order.supplier
        recent_start = today - timedelta(days=TREND_WINDOW_DAYS)
        previous_start = today - timedelta(days=TREND_WINDOW_DAYS * 2)
        recent = [item for item in shipments if recent_start <= item.actual_delivery_date <= today]
        previous = [item for item in shipments if previous_start <= item.actual_delivery_date < recent_start]
        enough = min(len(recent), len(previous)) >= MIN_TREND_ROWS_PER_WINDOW
        recent_rate = sum(_delay_days(item) > 0 for item in recent) / len(recent) if recent else None
        previous_rate = sum(_delay_days(item) > 0 for item in previous) / len(previous) if previous else None
        change = recent_rate - previous_rate if enough else None
        trend = (
            "insufficient_history" if not enough
            else "rising" if change >= 0.10
            else "falling" if change <= -0.10
            else "stable"
        )
        result.append({
            "supplier_code": supplier.code,
            "supplier_name": supplier.name,
            "trend": trend,
            "increasing_failure_risk": trend == "rising",
            "recent_late_rate_percent": round(recent_rate * 100, 1) if recent_rate is not None else None,
            "previous_late_rate_percent": round(previous_rate * 100, 1) if previous_rate is not None else None,
            "change_percentage_points": round(change * 100, 1) if change is not None else None,
            "recent_verified_deliveries": len(recent),
            "previous_verified_deliveries": len(previous),
            "minimum_per_window": MIN_TREND_ROWS_PER_WINDOW,
        })
    return sorted(result, key=lambda row: (row["trend"] != "rising", row["supplier_name"].casefold()))


def _material_shortage_forecast(shipment, late_probability, delay_model, deliveries, today):
    order = shipment.purchase_order
    lines = list(order.lines.select_related("material").all())
    order_materials_by_id = {}
    for line in lines:
        entry = order_materials_by_id.setdefault(line.material_id, [line.material, 0.0])
        entry[1] += float(line.quantity)
    order_materials = list(order_materials_by_id.values())
    if not order_materials:
        order_materials = [(order.material, float(order.quantity))]
    material_ids = [material.pk for material, _quantity in order_materials]
    inventory_rows = list(Inventory.objects.filter(material_id__in=material_ids).select_related("material"))
    stock = defaultdict(float)
    for inventory in inventory_rows:
        stock[inventory.material_id] += float(inventory.quantity)

    since = timezone.now() - timedelta(days=DEMAND_LOOKBACK_DAYS)
    demand_rows = InventoryMovement.objects.filter(
        inventory__material_id__in=material_ids,
        movement_type="issue",
        created_at__gte=since,
    ).values_list("inventory__material_id", "quantity_delta", "created_at")
    consumed = defaultdict(float)
    samples = defaultdict(int)
    earliest_issue = {}
    for material_id, delta, created_at in demand_rows:
        consumed[material_id] += abs(float(delta))
        samples[material_id] += 1
        issue_day = created_at.date()
        earliest_issue[material_id] = min(earliest_issue.get(material_id, issue_day), issue_day)

    days_until_eta = max(0, (shipment.eta - today).days) if shipment.eta else None
    conditional = _conditional_delay(delay_model, _features_for(shipment, deliveries)) if delay_model else None
    tree_delays = conditional.pop("tree_delay_estimates") if conditional else None
    materials = []
    valid_shortage_probabilities = []
    for material, _quantity in order_materials:
        observed_days = min(
            DEMAND_LOOKBACK_DAYS,
            max(0, (today - earliest_issue[material.pk]).days + 1),
        ) if material.pk in earliest_issue else 0
        avg_daily = consumed[material.pk] / observed_days if observed_days else 0.0
        enough_demand = samples[material.pk] >= 3 and observed_days >= 7 and avg_daily > 0
        coverage_days = stock[material.pk] / avg_daily if enough_demand else None
        baseline_shortage = bool(coverage_days is not None and days_until_eta is not None and coverage_days <= days_until_eta)
        shortage_probability = None
        reason = None
        if coverage_days is None:
            reason = f"At least 3 issue movements spanning 7 or more observed days in the last {DEMAND_LOOKBACK_DAYS} days are needed to estimate stock cover."
        elif delay_model is None or tree_delays is None:
            reason = f"At least {MIN_LATE_ROWS_FOR_DURATION} verified late deliveries are needed to estimate delay duration."
        elif baseline_shortage:
            reason = "Estimated stock cover ends before the current promised arrival, so any shortage is not attributable to a later delay alone."
        else:
            delay_budget = coverage_days - days_until_eta
            conditional_probability = float(np.mean(tree_delays > delay_budget))
            shortage_probability = late_probability * conditional_probability
            valid_shortage_probabilities.append(shortage_probability)
        materials.append({
            "material_sku": material.sku,
            "material_name": material.name,
            "on_hand": round(stock[material.pk], 2),
            "average_daily_issue": round(avg_daily, 2) if enough_demand else None,
            "issue_movements_used": samples[material.pk],
            "estimated_stock_cover_days": round(coverage_days, 1) if coverage_days is not None else None,
            "days_until_promised_arrival": days_until_eta,
            "baseline_shortage_before_eta": baseline_shortage,
            "shortage_due_to_delay_probability_percent": round(shortage_probability * 100, 1) if shortage_probability is not None else None,
            "estimate_note": reason,
        })
    # Use the highest material exposure; this does not assume independence between materials.
    overall = max(valid_shortage_probabilities) if valid_shortage_probabilities else None
    materials.sort(
        key=lambda row: (
            row["shortage_due_to_delay_probability_percent"] is not None,
            row["shortage_due_to_delay_probability_percent"] or -1,
        ),
        reverse=True,
    )
    highest_risk_material = next(
        (row for row in materials if row["shortage_due_to_delay_probability_percent"] is not None),
        None,
    )
    return {
        "probability_percent": round(overall * 100, 1) if overall is not None else None,
        "highest_risk_material": {
            "material_sku": highest_risk_material["material_sku"],
            "estimated_stock_cover_days": highest_risk_material["estimated_stock_cover_days"],
            "shortage_due_to_delay_probability_percent": highest_risk_material["shortage_due_to_delay_probability_percent"],
        } if highest_risk_material else None,
        "method": "highest per-material estimate; stock cover from recent recorded issue movements and conditional delay distribution",
        "inventory_scope": "on-hand quantity is aggregated across all recorded warehouses because shipment-to-warehouse allocation is not modeled",
        "materials": materials,
    }


def predictive_risk_report(today=None):
    """Train from verified outcomes and score current open shipments on request."""
    today = today or timezone.localdate()
    deliveries = _verified_deliveries()
    eligible_shipments = []
    excluded_count = 0
    for shipment in deliveries:
        order_date = _order_date(shipment)
        if shipment.eta < order_date or shipment.actual_delivery_date < order_date:
            excluded_count += 1
            continue
        eligible_shipments.append(shipment)
    valid_deliveries = eligible_shipments
    valid_rows = [{
            "shipment": shipment,
            "features": _features_for(shipment, valid_deliveries),
            "late": shipment.actual_delivery_date > shipment.eta,
            "delay_days": _delay_days(shipment),
        } for shipment in eligible_shipments]
    late_count = sum(row["late"] for row in valid_rows)
    on_time_count = len(valid_rows) - late_count
    summary = {
        "model_version": MODEL_VERSION,
        "model_type": "scikit-learn logistic regression with a conditional random-forest delay estimator",
        "training_status": "insufficient_data",
        "predictions_available": False,
        "is_independently_validated": False,
        "verified_shipments_used": len(valid_rows),
        "late_examples": late_count,
        "on_time_examples": on_time_count,
        "excluded_inconsistent_outcomes": excluded_count,
        "minimum_training_rows": MIN_TRAINING_ROWS,
        "minimum_rows_per_class": MIN_ROWS_PER_CLASS,
        "minimum_late_rows_for_delay_range": MIN_LATE_ROWS_FOR_DURATION,
        "training_cutoff_date": today.isoformat(),
        "predictions": [],
        "supplier_trends": _supplier_trends(valid_deliveries, today),
        "limitations": (
            "Probabilities are experimental and not independently calibrated. They use verified delivery history, "
            "current shipment attributes, and supplier outcomes known before the purchase-order date. "
            "They do not prove causation or replace planner review."
        ),
    }
    if len(valid_rows) < MIN_TRAINING_ROWS or min(late_count, on_time_count) < MIN_ROWS_PER_CLASS:
        summary["readiness_message"] = (
            f"Need at least {MIN_TRAINING_ROWS} consistent, approver-verified delivered shipments, "
            f"including {MIN_ROWS_PER_CLASS} late and {MIN_ROWS_PER_CLASS} on-time outcomes."
        )
        return summary

    training_frame = pd.DataFrame([row["features"] for row in valid_rows], columns=FEATURE_COLUMNS)
    labels = [int(row["late"]) for row in valid_rows]
    classifier = Pipeline([
        ("features", _preprocessor()),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)),
    ]).fit(training_frame, labels)
    delay_regressor = _fit_delay_regressor(valid_rows, [row["late"] for row in valid_rows])
    summary.update({
        "training_status": "ready",
        "predictions_available": True,
        "delay_range_available": delay_regressor is not None,
        "delay_range_status": (
            "ready" if delay_regressor else
            f"Need at least {MIN_LATE_ROWS_FOR_DURATION} verified late shipments for a duration estimate."
        ),
    })

    open_shipments = list(
        Shipment.objects.filter(status__in=["planned", "in_transit", "delayed", "at_risk"], eta__isnull=False)
        .select_related("purchase_order", "purchase_order__supplier")
        .prefetch_related("purchase_order__lines__material")
        .order_by("eta", "reference")
    )
    predictions = []
    for shipment in open_shipments:
        features = _features_for(shipment, valid_deliveries)
        frame = pd.DataFrame([features], columns=FEATURE_COLUMNS)
        probabilities = classifier.predict_proba(frame)[0]
        late_probability = float(probabilities[list(classifier.classes_).index(1)])
        model_confidence = max(probabilities)
        delay_estimate = _conditional_delay(delay_regressor, features) if delay_regressor else None
        if delay_estimate:
            delay_estimate.pop("tree_delay_estimates", None)
        shortage = _material_shortage_forecast(shipment, late_probability, delay_regressor, valid_deliveries, today)
        predictions.append({
            "shipment_id": str(shipment.pk),
            "shipment_reference": shipment.reference,
            "purchase_order_number": shipment.purchase_order.number,
            "supplier_code": shipment.purchase_order.supplier.code,
            "supplier_name": shipment.purchase_order.supplier.name,
            "eta": shipment.eta.isoformat(),
            "late_probability_percent": round(late_probability * 100, 1),
            "model_confidence_percent": round(float(model_confidence) * 100, 1),
            "confidence_basis": "maximum class probability; probabilities are not independently calibrated",
            "expected_delay_days": delay_estimate["expected_delay_days"] if delay_estimate else None,
            "expected_delay_range_days": delay_estimate["delay_range_days"] if delay_estimate else None,
            "delay_estimate_is_conditional_on_late_arrival": bool(delay_estimate),
            "material_shortage": shortage,
            "factors": _local_factors(classifier, features),
        })
    summary["predictions"] = predictions
    return summary
