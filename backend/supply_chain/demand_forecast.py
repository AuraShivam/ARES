"""Demand forecasts and advisory inventory recommendations from dated issue history."""

import math
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
from django.db.models import Sum
from django.utils import timezone
from sklearn.ensemble import RandomForestRegressor

from .models import Disruption, Inventory, InventoryMovement, Material, PurchaseOrder


MODEL_VERSION = "ARES material demand forecast v1"
HORIZONS = (7, 30, 90)
LOOKBACK_DAYS = 180
MIN_HISTORY_DAYS = 60
MIN_ISSUE_DAYS = 10
LAG_DAYS = 28
ACTIVE_PO_STATUSES = ("approved", "in_transit", "delayed")


def _features(values, index, weekday):
    recent_7 = values[max(0, index - 7):index]
    recent_28 = values[max(0, index - LAG_DAYS):index]
    return [
        float(values[index - 1]),
        float(values[index - 7]),
        float(values[index - 14]),
        float(values[index - 28]),
        float(np.mean(recent_7)),
        float(np.mean(recent_28)),
        float(np.std(recent_28)),
        math.sin(2 * math.pi * weekday / 7),
        math.cos(2 * math.pi * weekday / 7),
    ]


def _series_for_material(history, today):
    if not history:
        return None, None, 0
    first_day = min(row["occurred_at"] for row in history)
    start = max(first_day, today - timedelta(days=LOOKBACK_DAYS - 1))
    index = pd.date_range(start=start, end=today, freq="D")
    daily = pd.Series(0.0, index=index)
    observed_days = set()
    for row in history:
        day = row["occurred_at"]
        if start <= day <= today:
            daily.loc[pd.Timestamp(day)] += abs(float(row["quantity"]))
            observed_days.add(day)
    coverage_days = (today - start).days + 1
    return daily, start, len(observed_days)


def _fit_and_forecast(daily):
    values = daily.to_numpy(dtype=float)
    features, targets = [], []
    for index in range(LAG_DAYS, len(values)):
        features.append(_features(values, index, daily.index[index].weekday()))
        targets.append(values[index])
    if len(features) < 24:
        return None
    model = RandomForestRegressor(
        n_estimators=100,
        min_samples_leaf=2,
        max_features=0.8,
        random_state=42,
        n_jobs=1,
    )
    model.fit(features, targets)
    rolling = list(values)
    future = []
    next_day = daily.index[-1] + pd.Timedelta(days=1)
    for offset in range(90):
        index = len(rolling)
        day = next_day + pd.Timedelta(days=offset)
        estimate = max(0.0, float(model.predict([_features(np.asarray(rolling), index, day.weekday())])[0]))
        future.append(estimate)
        rolling.append(estimate)
    return future


def _open_inbound(material_id, today):
    inbound = defaultdict(float)
    orders = (
        PurchaseOrder.objects.filter(status__in=ACTIVE_PO_STATUSES, expected_date__isnull=False)
        .select_related("material")
        .prefetch_related("lines")
    )
    for order in orders:
        if order.expected_date < today:
            arrival = today
        else:
            arrival = order.expected_date
        lines = list(order.lines.all())
        if lines:
            quantity = sum(
                (line.quantity - line.received_quantity for line in lines if line.material_id == material_id),
                start=0,
            )
        else:
            quantity = order.quantity if order.material_id == material_id else 0
        if quantity > 0:
            inbound[arrival] += float(quantity)
    return inbound


def _observed_receipt_lead_times(today):
    receipt_rows = (
        InventoryMovement.objects.filter(
            movement_type="receipt",
            occurred_at__lte=today,
            purchase_order__isnull=False,
        )
        .select_related("inventory__material", "purchase_order__supplier")
        .order_by("occurred_at")
    )
    lead_times = defaultdict(dict)
    for movement in receipt_rows:
        order = movement.purchase_order
        ordered_at = order.ordered_at or order.created_at.date()
        elapsed_days = (movement.occurred_at - ordered_at).days
        if elapsed_days < 1:
            continue
        key = (movement.inventory.material_id, order.pk)
        previous = lead_times[movement.inventory.material_id].get(order.pk)
        if previous is None or movement.occurred_at < previous[1]:
            lead_times[key[0]][key[1]] = (elapsed_days, movement.occurred_at, order.supplier_id)
    return lead_times


def _stockout_projection(on_hand, forecast, inbound, today):
    balance = float(on_hand)
    for index, demand in enumerate(forecast):
        day = today + timedelta(days=index + 1)
        balance += inbound.get(day, 0.0)
        balance -= demand
        if balance <= 0:
            return {"date": day.isoformat(), "days": index + 1}
    return {"date": None, "days": None}


def demand_forecast_report(today=None):
    today = today or timezone.localdate()
    history_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    issue_rows = list(
        InventoryMovement.objects.filter(
            movement_type="issue",
            occurred_at__gte=history_start,
            occurred_at__lte=today,
        )
        .values("inventory__material_id", "occurred_at")
        .annotate(quantity=Sum("quantity_delta"))
        .order_by("occurred_at")
    )
    history = defaultdict(list)
    for row in issue_rows:
        history[row["inventory__material_id"]].append({
            "occurred_at": row["occurred_at"],
            "quantity": row["quantity"],
        })

    balances = defaultdict(float)
    reorder_points = defaultdict(float)
    for row in Inventory.objects.values("material_id", "quantity", "reorder_point"):
        balances[row["material_id"]] += float(row["quantity"])
        reorder_points[row["material_id"]] += float(row["reorder_point"])

    active_disruption_suppliers = set(
        Disruption.objects.filter(
            status__in=("open", "review", "mitigating"),
            affected_supplier_id__isnull=False,
        ).values_list("affected_supplier_id", flat=True)
    )
    receipt_lead_times = _observed_receipt_lead_times(today)

    results = []
    for material in Material.objects.select_related("preferred_supplier").all():
        rows = history.get(material.pk, [])
        daily, start, issue_days = _series_for_material(rows, today)
        coverage_days = (today - start).days + 1 if start else 0
        ready = bool(daily is not None and coverage_days >= MIN_HISTORY_DAYS and issue_days >= MIN_ISSUE_DAYS)
        forecasts = _fit_and_forecast(daily) if ready else None
        ready = ready and forecasts is not None
        on_hand = balances[material.pk]
        reorder_point = reorder_points[material.pk]
        observed = [
            row for row in receipt_lead_times.get(material.pk, {}).values()
            if material.preferred_supplier_id and row[2] == material.preferred_supplier_id
        ]
        observed.sort(key=lambda row: row[1], reverse=True)
        if len(observed) >= 3:
            recent_receipts = observed[:6]
            lead_time = max(1, min(365, round(sum(row[0] for row in recent_receipts) / len(recent_receipts))))
            lead_time_basis = f"average of {len(recent_receipts)} linked receipt records"
        elif material.preferred_supplier_id:
            lead_time = material.preferred_supplier.lead_time_days
            lead_time_basis = "preferred supplier profile"
        else:
            lead_time = 14
            lead_time_basis = "14-day planning default; no preferred supplier"
        inbound = _open_inbound(material.pk, today)
        inbound_within_lead = sum(quantity for day, quantity in inbound.items() if day <= today + timedelta(days=lead_time))
        stockout = _stockout_projection(on_hand, forecasts, inbound, today) if ready else {"date": None, "days": None}

        if ready:
            history_values = daily.to_numpy(dtype=float)
            demand_std = float(np.std(history_values[-min(len(history_values), 90):]))
            lead_forecast = sum(forecasts[:lead_time])
            if lead_time > len(forecasts):
                lead_forecast += (lead_time - len(forecasts)) * float(np.mean(forecasts[-28:]))
            safety_stock = 1.65 * demand_std * math.sqrt(lead_time)
            reorder_quantity = max(0, math.ceil(lead_forecast + safety_stock - on_hand - inbound_within_lead))
            horizon_totals = {
                str(horizon): round(sum(forecasts[:horizon]), 2)
                for horizon in HORIZONS
            }
            confidence = "high" if coverage_days >= 150 and issue_days >= 30 else "moderate"
            recent_issue_days = sum(1 for row in rows if row["occurred_at"] >= today - timedelta(days=89))
            possible_obsolete = bool(on_hand > 0 and coverage_days >= 90 and recent_issue_days == 0)
            recommendation = "No additional order is indicated by the forecast and open purchase orders."
            if reorder_quantity:
                recommendation = f"Review a reorder of {reorder_quantity:g} {material.unit} to cover estimated lead-time demand and safety stock."
            if stockout["days"] is not None and stockout["days"] <= lead_time:
                recommendation = f"Urgent review: projected stockout in {stockout['days']} days is earlier than the {lead_time}-day supplier lead time."
            linked_disruption = bool(material.preferred_supplier_id in active_disruption_suppliers)
            if linked_disruption:
                recommendation += " An open disruption is linked to the preferred supplier; review this material in the disruption workflow."
            readiness_message = "Forecast uses dated issue movements and assumes the supplied history is complete."
        else:
            horizon_totals = {str(horizon): None for horizon in HORIZONS}
            confidence = "unavailable"
            possible_obsolete = None
            reorder_quantity = None
            safety_stock = None
            recommendation = "Import dated issue movements with at least 60 days of coverage and 10 distinct consumption days to enable forecasting."
            linked_disruption = bool(material.preferred_supplier_id in active_disruption_suppliers)
            if linked_disruption:
                recommendation += " An open disruption is linked to the preferred supplier; review this material in the disruption workflow."
            if daily is None:
                readiness_message = "No dated issue movements are available for this material. Current stock alone cannot support demand forecasting."
            elif coverage_days < MIN_HISTORY_DAYS:
                readiness_message = f"Only {coverage_days} days of issue history are available; at least {MIN_HISTORY_DAYS} days are required."
            else:
                readiness_message = f"Only {issue_days} distinct consumption days are available; at least {MIN_ISSUE_DAYS} are required."

        results.append({
            "material_id": str(material.pk),
            "material_sku": material.sku,
            "material_name": material.name,
            "unit": material.unit,
            "criticality": material.criticality,
            "on_hand": round(on_hand, 2),
            "reorder_point": round(reorder_point, 2),
            "below_reorder_point": on_hand <= reorder_point,
            "lead_time_days": lead_time,
            "lead_time_basis": lead_time_basis,
            "linked_receipt_orders": len(observed),
            "preferred_supplier": material.preferred_supplier.name if material.preferred_supplier_id else None,
            "history_coverage_days": coverage_days,
            "consumption_days": issue_days,
            "last_issue_date": max((row["occurred_at"] for row in rows), default=None).isoformat() if rows else None,
            "forecast_available": ready,
            "readiness_message": readiness_message,
            "model_confidence": confidence,
            "forecast_units": horizon_totals,
            "stockout_date": stockout["date"],
            "days_until_stockout": stockout["days"],
            "recommended_reorder_quantity": reorder_quantity,
            "safety_stock_units": round(safety_stock, 2) if safety_stock is not None else None,
            "possible_idle_inventory": possible_obsolete,
            "linked_supplier_disruption": linked_disruption,
            "recommendation": recommendation,
        })

    ready_count = sum(1 for item in results if item["forecast_available"])
    return {
        "model_version": MODEL_VERSION,
        "generated_at": timezone.now().isoformat(),
        "as_of_date": today.isoformat(),
        "horizons_days": list(HORIZONS),
        "materials_total": len(results),
        "materials_with_forecast": ready_count,
        "materials_without_sufficient_history": len(results) - ready_count,
        "minimum_history_days": MIN_HISTORY_DAYS,
        "minimum_consumption_days": MIN_ISSUE_DAYS,
        "method": "Per-material random-forest regression over daily issue quantities, recent lags, rolling averages, variability, and weekday; future days are forecast recursively.",
        "limitations": "Confidence is a data-coverage indicator, not a calibrated probability. Forecasts assume dated issue movements represent complete consumption history; they are advisory and do not automatically create purchase orders.",
        "materials": results,
    }
