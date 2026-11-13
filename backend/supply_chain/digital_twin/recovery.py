"""Evidence-grounded recovery option comparison for isolated digital-twin scenarios."""

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import math
from statistics import median

from django.utils import timezone

from supply_chain.models import Inventory, Material, PurchaseOrder, Shipment, Supplier, Warehouse


DEFAULT_RANKING_WEIGHTS = {
    "recovery_time": Decimal("35"),
    "cost": Decimal("25"),
    "service_level": Decimal("30"),
    "supplier_risk": Decimal("10"),
}
EARTH_RADIUS_KM = 6371.0088
MAX_AUTOMATIC_CANDIDATES = 50


def _decimal(value):
    return Decimal(str(value)) if value not in (None, "") else None


def _materials_on_order(order):
    lines = list(order.lines.select_related("material"))
    if lines:
        return [(line.material, line.quantity, line.unit_price) for line in lines]
    return [(order.material, order.quantity, order.unit_price)]


def _outstanding_materials(order):
    lines = list(order.lines.select_related("material"))
    if lines:
        return [(line.material, max(Decimal("0"), line.quantity - line.received_quantity)) for line in lines]
    return [(order.material, max(Decimal("0"), order.quantity))]


def _verified_supplier_profiles(materials, failed_supplier_id=None):
    material_by_id = {material.pk: material for material in materials}
    if not material_by_id:
        return {}
    shipments = Shipment.objects.filter(
        delivery_outcome_verified=True,
        status="delivered",
        actual_delivery_date__isnull=False,
        purchase_order__supplier__status__in=("active", "watch"),
    ).select_related("purchase_order", "purchase_order__supplier").prefetch_related("purchase_order__lines__material").order_by("-actual_delivery_date")[:1000]
    profiles = defaultdict(list)
    for shipment in shipments:
        order = shipment.purchase_order
        supplier = order.supplier
        if failed_supplier_id and str(supplier.pk) == str(failed_supplier_id):
            continue
        for material, quantity, unit_price in _materials_on_order(order):
            if material.pk not in material_by_id:
                continue
            expected = shipment.eta or order.expected_date
            profiles[material.pk, supplier.pk].append({
                "supplier": supplier,
                "shipment": shipment,
                "order": order,
                "quantity": quantity,
                "unit_price": unit_price,
                "currency": order.currency,
                "lead_days": (shipment.actual_delivery_date - order.ordered_at).days if order.ordered_at else None,
                "late": bool(expected and shipment.actual_delivery_date > expected),
            })
    return profiles


def _profile_summary(rows):
    leads = [row["lead_days"] for row in rows if row["lead_days"] is not None and row["lead_days"] >= 0]
    priced = [row for row in rows if row["unit_price"] > 0]
    currencies = {row["currency"] for row in priced}
    unit_cost = None
    currency = None
    if priced and len(currencies) == 1:
        unit_cost = str(median([row["unit_price"] for row in priced]).quantize(Decimal("0.01")))
        currency = next(iter(currencies))
    return {
        "verified_deliveries": len(rows),
        "verified_late_deliveries": sum(1 for row in rows if row["late"]),
        "last_verified_delivery": max(row["shipment"].actual_delivery_date for row in rows).isoformat(),
        "median_observed_lead_days": round(median(leads), 1) if leads else None,
        "historical_max_order_quantity": str(max((row["quantity"] for row in rows), default=Decimal("0"))),
        "historical_unit_cost": unit_cost,
        "historical_cost_currency": currency,
        "current_supplier_capacity": "unknown",
    }


def _scenario_gap(row):
    simulated = row["simulated"]
    projected = _decimal(simulated.get("projected_available"))
    if projected is not None:
        return max(Decimal("0"), -projected)
    return max(
        _decimal(simulated.get("deferred_inbound")) or Decimal("0"),
        _decimal(simulated.get("removed_on_hand")) or Decimal("0"),
    )


def _route_length_km(geometry):
    if geometry.get("type") == "LineString":
        lines = [geometry.get("coordinates") or []]
    else:
        lines = geometry.get("coordinates") or []
    distance = 0.0
    for line in lines:
        for start, end in zip(line, line[1:]):
            lon1, lat1 = map(math.radians, start[:2])
            lon2, lat2 = map(math.radians, end[:2])
            delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
            value = (math.sin(delta_lat / 2) ** 2
                     + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2)
            distance += 2 * EARTH_RADIUS_KM * math.asin(min(1, math.sqrt(value)))
    return round(distance, 2)


def _weighted_rank(strategies, weights):
    cost_values = defaultdict(list)
    time_values = []
    for strategy in strategies:
        metrics = strategy.get("metrics") or {}
        if metrics.get("recovery_days") is not None:
            time_values.append(float(metrics["recovery_days"]))
        if metrics.get("estimated_cost") is not None and metrics.get("currency"):
            key = (metrics["currency"], metrics.get("cost_basis"))
            cost_values[key].append(float(metrics["estimated_cost"]))
    min_time, max_time = (min(time_values), max(time_values)) if time_values else (None, None)
    cost_ranges = {key: (min(values), max(values)) for key, values in cost_values.items() if len(values) >= 2}

    ranked = []
    unranked = []
    for strategy in strategies:
        metrics = strategy.get("metrics") or {}
        components = {}
        days = metrics.get("recovery_days")
        if days is not None and len(time_values) >= 2:
            components["recovery_time"] = 100.0 if min_time == max_time else 100 * (max_time - float(days)) / (max_time - min_time)
        cost = metrics.get("estimated_cost")
        currency = metrics.get("currency")
        cost_key = (currency, metrics.get("cost_basis"))
        if cost is not None and cost_key in cost_ranges:
            low, high = cost_ranges[cost_key]
            components["cost"] = 100.0 if low == high else 100 * (high - float(cost)) / (high - low)
        if metrics.get("service_level_percent") is not None:
            components["service_level"] = max(0.0, min(100.0, float(metrics["service_level_percent"])))
        if metrics.get("supplier_risk_score") is not None:
            components["supplier_risk"] = 100.0 - max(0.0, min(100.0, float(metrics["supplier_risk_score"])))
        applied = sum((weights[key] for key in components), Decimal("0"))
        if applied > 0:
            score = sum(float(weights[key]) * value for key, value in components.items()) / float(applied)
            strategy["ranking"] = {
                "score": round(score, 1),
                "ranked_weight_percent": float(applied),
                "components": {key: round(value, 1) for key, value in components.items()},
                "weights": {key: float(weights[key]) for key in components},
                "status": "partial" if applied < 100 else "scored",
            }
            ranked.append(strategy)
        else:
            strategy["ranking"] = {"score": None, "ranked_weight_percent": 0, "components": {},
                                   "weights": {}, "status": "unranked_missing_metrics"}
            unranked.append(strategy)
    ranked.sort(key=lambda item: (-item["ranking"]["score"], item["name"]))
    for index, strategy in enumerate(ranked, start=1):
        strategy["ranking"]["rank"] = index
    return ranked + unranked


def compare_recovery_options(scenario, target, materials, projections):
    """Compare explicit what-if options and expose evidence-only candidates from history."""
    weights = dict(DEFAULT_RANKING_WEIGHTS)
    weights.update({key: _decimal(value) for key, value in scenario.get("ranking_weights", {}).items()})
    material_by_id = {str(material.pk): material for material in materials}
    baseline_projections = deepcopy(projections)
    projection_by_id = {row["material_id"]: row for row in baseline_projections}
    today = timezone.localdate()
    horizon_end = today + timedelta(days=scenario["horizon_days"])
    options = scenario.get("recovery_options", [])
    strategies = []
    automatic_candidate_count = 0
    omitted_candidate_count = 0
    unavailable = []

    failed_supplier_id = target.pk if scenario["scenario_type"] == "supplier_failure" else None
    profiles = _verified_supplier_profiles(materials, failed_supplier_id=failed_supplier_id)
    for (material_id, supplier_id), rows in profiles.items():
        material = material_by_id[str(material_id)]
        supplier = rows[0]["supplier"]
        if material.preferred_supplier_id == supplier.pk and scenario["scenario_type"] != "supplier_failure":
            continue
        profile = _profile_summary(rows)
        projection = projection_by_id.get(str(material_id))
        gap = _scenario_gap(projection) if projection else Decimal("0")
        metrics = {"recovery_days": profile["median_observed_lead_days"],
                   "estimated_cost": None, "currency": profile["historical_cost_currency"],
                   "cost_basis": "historical_verified_purchase_order_price",
                   "supplier_risk_score": supplier.risk_score}
        if profile["historical_unit_cost"] is not None and gap > 0:
            metrics["estimated_cost"] = str((_decimal(profile["historical_unit_cost"]) * gap).quantize(Decimal("0.01")))
        candidate = {
            "id": f"verified-supplier:{material_id}:{supplier_id}",
            "strategy_type": "emergency_procurement",
            "name": f"Review verified supplier {supplier.name} for {material.sku}",
            "status": "candidate_for_review",
            "material_id": str(material_id),
            "supplier": {"id": str(supplier.pk), "code": supplier.code, "name": supplier.name,
                         "status": supplier.status, "risk_score": supplier.risk_score},
            "metrics": metrics,
            "evidence": {**profile, "basis": "ARES approver-verified delivered shipment history",
                         "scenario_gap_quantity": str(gap) if gap > 0 else None},
            "limitations": ["A historical verified delivery does not confirm current supplier capacity or willingness.",
                            "Any cost is based on past purchase records, not a current quote."],
        }
        automatic_candidate_count += 1
        if automatic_candidate_count <= MAX_AUTOMATIC_CANDIDATES:
            strategies.append(candidate)
        else:
            omitted_candidate_count += 1

    if scenario["scenario_type"] == "warehouse_failure":
        affected_stock = Inventory.objects.filter(warehouse=target, material_id__in=[item.pk for item in materials]).select_related("material")
        destinations = list(Warehouse.objects.filter(active=True).exclude(pk=target.pk))
        for inventory in affected_stock:
            for destination in destinations:
                candidate = {
                    "id": f"redistribution-candidate:{inventory.material_id}:{destination.pk}",
                    "strategy_type": "inventory_redistribution",
                    "name": f"Move {inventory.material.sku} from {target.name} to {destination.name}",
                    "status": "candidate_needs_operating_inputs",
                    "material_id": str(inventory.material_id),
                    "source_warehouse": {"id": str(target.pk), "code": target.code, "name": target.name},
                    "destination_warehouse": {"id": str(destination.pk), "code": destination.code, "name": destination.name},
                    "metrics": {"quantity_available_to_rescue": str(inventory.quantity),
                                "recovery_days": None, "estimated_cost": None, "currency": None},
                    "evidence": {"source_on_hand": str(inventory.quantity),
                                 "source_reorder_point": str(inventory.reorder_point),
                                 "basis": "current ARES inventory balance"},
                    "limitations": ["Transfer lead time and cost are not recorded.",
                                    "Destination storage capacity is not modeled."],
                }
                automatic_candidate_count += 1
                if automatic_candidate_count <= MAX_AUTOMATIC_CANDIDATES:
                    strategies.append(candidate)
                else:
                    omitted_candidate_count += 1

    option_groups = []
    group_indexes = {}
    for option_index, option in enumerate(options, start=1):
        combination_name = option.get("combination_name")
        group_key = f"combination:{combination_name}" if combination_name else f"option:{option_index}"
        if group_key not in group_indexes:
            group_indexes[group_key] = len(option_groups)
            option_groups.append({"name": combination_name, "options": []})
        option_groups[group_indexes[group_key]]["options"].append((option_index, option))

    route_option_count = 0
    for group in option_groups:
        option_projections = deepcopy(baseline_projections)
        option_projection_by_id = {row["material_id"]: row for row in option_projections}
        components = []
        transfer_state = {}
        for option_index, option in group["options"]:
            strategy_type = option["strategy_type"]
            if strategy_type == "inventory_redistribution":
                component = _simulate_redistribution(scenario, target, option, material_by_id, option_projection_by_id, horizon_end, option_index, transfer_state)
            elif strategy_type == "emergency_procurement":
                component = _simulate_procurement(scenario, option, material_by_id, option_projection_by_id, profiles, horizon_end, option_index)
            else:
                component = _simulate_route_alternative(scenario, target, option, option_projection_by_id, horizon_end, option_index)
                route_option_count += 1
            components.append(component)
        if len(components) == 1:
            strategy = components[0]
        else:
            strategy = _combine_recovery_strategies(
                group["name"], components, baseline_projections, option_projections,
            )
        strategy["result"]["material_projection_after_recovery"] = option_projections
        strategies.append(strategy)

    if scenario["scenario_type"] == "route_disruption" and route_option_count == 0:
        unavailable.append({"strategy_type": "route_alternative", "status": "unavailable",
                            "reason": "No sourced alternative route and transit-time input was supplied; ARES does not invent routes or use a routing provider."})
    if not any(item["strategy_type"] == "inventory_redistribution" for item in strategies):
        unavailable.append({"strategy_type": "inventory_redistribution", "status": "not_evaluated",
                            "reason": "A source/destination warehouse pair and transfer assumption are required; network-wide inventory alone does not identify where demand can be served."})
    if not any(item["strategy_type"] == "emergency_procurement" for item in strategies):
        unavailable.append({"strategy_type": "emergency_procurement", "status": "not_evaluated",
                            "reason": "No approver-verified delivered history for an alternate supplier/material pair was found in the current scenario scope."})

    ranked = _weighted_rank(strategies, weights)
    return {
        "label": "SIMULATED RECOVERY COMPARISON",
        "ranking_policy": {
            "weights": {key: float(value) for key, value in weights.items()},
            "formula": "Weighted mean of available metric scores; missing metrics are omitted and the applied weight coverage is shown per strategy.",
            "metric_direction": {"recovery_time": "shorter is better", "cost": "lower is better within the same currency",
                                 "service_level": "higher is better", "supplier_risk": "lower current supplier risk score is better"},
            "cost_comparison": "Only strategies sharing at least two estimates with the same currency and cost basis receive a comparative cost score.",
            "not_a_recommendation": "A ranking compares supplied assumptions and recorded evidence; it does not approve or execute a recovery action.",
        },
        "baseline": {"scenario_type": scenario["scenario_type"], "horizon_end": horizon_end.isoformat(),
                     "material_projections": baseline_projections},
        "strategies": ranked,
        "unavailable_strategies": unavailable,
        "operator_supplied_options": len(options),
        "automatic_candidate_limit": MAX_AUTOMATIC_CANDIDATES,
        "omitted_automatic_candidates": omitted_candidate_count,
    }


def _simulate_redistribution(scenario, target, option, material_by_id, projection_by_id, horizon_end, option_index, transfer_state):
    material_id = str(option["material_id"])
    material = material_by_id.get(material_id)
    source = Warehouse.objects.filter(pk=option["source_warehouse_id"]).first()
    destination = Warehouse.objects.filter(pk=option["destination_warehouse_id"]).first()
    if material is None or source is None or destination is None:
        raise ValueError("Redistribution must reference a scenario material and existing warehouses.")
    if not source.active or not destination.active:
        raise ValueError("Redistribution source and destination warehouses must be active in ARES.")
    if source.pk == destination.pk:
        raise ValueError("Redistribution source and destination must differ.")
    if scenario["scenario_type"] == "warehouse_failure" and destination.pk == target.pk:
        raise ValueError("A warehouse-failure recovery cannot transfer stock into the failed warehouse.")
    inventory = Inventory.objects.filter(material=material, warehouse=source).first()
    if inventory is None:
        raise ValueError("No inventory balance exists for the selected material at the source warehouse.")
    scenario_warehouse_failure = scenario["scenario_type"] == "warehouse_failure" and source.pk == target.pk
    source_key = (str(material.pk), str(source.pk))
    state = transfer_state.setdefault(source_key, {
        "used": Decimal("0"),
        "available": inventory.quantity if scenario_warehouse_failure else max(Decimal("0"), inventory.quantity - inventory.reorder_point),
    })
    if option.get("release_reorder_buffer") and not scenario_warehouse_failure:
        state["available"] = inventory.quantity
    quantity = _decimal(option["quantity"])
    available = max(Decimal("0"), state["available"] - state["used"])
    if quantity > available:
        raise ValueError(f"Combined transfer quantity exceeds the source balance available under the selected buffer policy ({available}).")
    state["used"] += quantity
    projection = projection_by_id[material_id]
    recovered = quantity if scenario_warehouse_failure else Decimal("0")
    if recovered:
        _apply_available_delta(projection, recovered)
    cost = _decimal(option.get("estimated_transfer_cost"))
    metrics = {"recovery_days": option["transfer_days"],
               "estimated_cost": str(cost) if cost is not None else None,
               "currency": option.get("currency"),
               "cost_basis": "operator_supplied_estimate" if cost is not None else None}
    if scenario_warehouse_failure:
        lost = _decimal(projection["simulated"].get("removed_on_hand")) or Decimal("0")
        metrics["service_level_percent"] = float(min(Decimal("100"), quantity / lost * Decimal("100"))) if lost > 0 else None
    return {
        "id": f"operator-redistribution:{option_index}:{material_id}:{source.pk}:{destination.pk}",
        "strategy_type": "inventory_redistribution", "name": f"Transfer {quantity} {material.unit} of {material.sku}",
        "status": "hypothetical", "material_id": material_id,
        "source_warehouse": {"id": str(source.pk), "code": source.code, "name": source.name},
        "destination_warehouse": {"id": str(destination.pk), "code": destination.code, "name": destination.name},
        "metrics": metrics,
        "result": {"quantity_transferred": str(quantity), "network_available_quantity_recovered": str(recovered),
                   "destination_capacity_modeled": False},
        "evidence": {"source_on_hand": str(inventory.quantity), "source_reorder_point": str(inventory.reorder_point),
                     "reorder_buffer_released": bool(option.get("release_reorder_buffer")) and not scenario_warehouse_failure,
                     "source_reference": option["source_reference"]},
        "limitations": (["For a warehouse-failure scenario, this assumes stock can be moved before the site becomes unavailable."] if scenario_warehouse_failure else
                        ["This transfer changes location only; network-wide stock totals do not increase.",
                         "ARES has no location-specific demand allocation, so incremental fulfilment coverage cannot be calculated."]),
    }


def _simulate_procurement(scenario, option, material_by_id, projection_by_id, profiles, horizon_end, option_index):
    material_id = str(option["material_id"])
    supplier = Supplier.objects.filter(pk=option["supplier_id"]).first()
    material = material_by_id.get(material_id)
    if material is None or supplier is None:
        raise ValueError("Emergency procurement must reference a scenario material and an existing supplier.")
    if supplier.status == "blocked":
        raise ValueError("A blocked supplier cannot be used as a recovery candidate.")
    if scenario["scenario_type"] == "supplier_failure" and str(supplier.pk) == str(target_supplier_id(scenario)):
        raise ValueError("The failed supplier cannot also be selected as an emergency-procurement alternative.")
    history = profiles.get((material.pk, supplier.pk), [])
    if not history:
        raise ValueError("Emergency procurement requires at least one approver-verified delivered shipment for this supplier/material pair.")
    projection = projection_by_id[material_id]
    quantity = _decimal(option["quantity"])
    lead_days = option["lead_time_days"]
    arrival_date = timezone.localdate() + timedelta(days=lead_days)
    by_horizon = arrival_date <= horizon_end
    gap = _scenario_gap(projection)
    if by_horizon:
        _apply_available_delta(projection, quantity)
    profile = _profile_summary(history)
    unit_cost = _decimal(option.get("estimated_unit_cost"))
    cost_basis = "operator-supplied current estimate"
    currency = option.get("currency")
    if unit_cost is None and profile["historical_unit_cost"] is not None:
        unit_cost = _decimal(profile["historical_unit_cost"])
        currency = profile["historical_cost_currency"]
        cost_basis = "historical verified purchase-order price; not a current quote"
    estimated_cost = (unit_cost * quantity).quantize(Decimal("0.01")) if unit_cost is not None else None
    service = min(Decimal("100"), quantity / gap * Decimal("100")) if gap > 0 and by_horizon else Decimal("0") if gap > 0 else None
    return {
        "id": f"operator-procurement:{option_index}:{material.pk}:{supplier.pk}",
        "strategy_type": "emergency_procurement", "name": f"Emergency procurement · {supplier.name} · {material.sku}",
        "status": "hypothetical", "material_id": material_id,
        "supplier": {"id": str(supplier.pk), "code": supplier.code, "name": supplier.name,
                     "status": supplier.status, "risk_score": supplier.risk_score},
        "metrics": {"recovery_days": lead_days, "estimated_cost": str(estimated_cost) if estimated_cost is not None else None,
                    "currency": currency, "cost_basis": "historical_verified_purchase_order_price" if cost_basis.startswith("historical") else "operator_supplied_estimate",
                    "service_level_percent": float(service) if service is not None else None,
                    "supplier_risk_score": supplier.risk_score},
        "result": {"assumed_quantity": str(quantity), "assumed_arrival_date": arrival_date.isoformat(),
                   "arrives_within_horizon": by_horizon, "network_available_quantity_added": str(quantity if by_horizon else Decimal("0")),
                   "projected_material_available": projection["simulated"].get("projected_available") or projection["simulated"].get("supply_only_available")},
        "evidence": {**profile, "supplier_capacity_confirmed": False,
                     "source_reference": option["source_reference"], "cost_basis": cost_basis},
        "limitations": ["The scenario assumes the operator-entered quantity is available; current supplier capacity and willingness are not modeled.",
                        "Historical supplier performance and prices are evidence, not a current offer or guaranteed lead time."],
    }


def _simulate_route_alternative(scenario, target, option, projection_by_id, horizon_end, option_index):
    if scenario["scenario_type"] != "route_disruption" or str(option["shipment_id"]) != str(target.pk):
        raise ValueError("A route alternative must target the selected shipment in a route-disruption scenario.")
    shipment = target
    order = shipment.purchase_order
    arrival_date = timezone.localdate() + timedelta(days=option["transit_days"])
    baseline_date = shipment.eta or order.expected_date
    baseline_simulated_date = baseline_date + timedelta(days=scenario["delay_days"]) if baseline_date else None
    can_restore_inbound = bool(
        arrival_date <= horizon_end
        and (baseline_simulated_date is None or baseline_simulated_date > horizon_end)
    )
    recovered = {}
    for material, remaining in _outstanding_materials(order):
        material_id = str(material.pk)
        projection = projection_by_id.get(material_id)
        quantity = max(Decimal("0"), remaining) if can_restore_inbound and projection else Decimal("0")
        if quantity:
            _apply_available_delta(projection, quantity)
        recovered[material_id] = str(quantity)
    cost = _decimal(option.get("estimated_transfer_cost"))
    days_saved = max(0, (baseline_simulated_date - arrival_date).days) if baseline_simulated_date else None
    return {
        "id": f"operator-route:{option_index}:{shipment.pk}:{option['source_reference']}",
        "strategy_type": "route_alternative", "name": f"Alternate route · {option['source_reference']}",
        "status": "hypothetical", "shipment_id": str(shipment.pk),
        "metrics": {"recovery_days": option["transit_days"], "estimated_cost": str(cost) if cost is not None else None,
                    "currency": option.get("currency"),
                    "cost_basis": "operator_supplied_estimate" if cost is not None else None,
                    "service_level_percent": 100.0 if can_restore_inbound else 0.0},
        "result": {"route_geometry": option["route_geometry"], "route_distance_km": _route_length_km(option["route_geometry"]),
                   "assumed_arrival_date": arrival_date.isoformat(),
                   "baseline_simulated_arrival_date": baseline_simulated_date.isoformat() if baseline_simulated_date else None,
                   "days_saved_vs_scenario": days_saved, "inbound_restored_within_horizon": can_restore_inbound,
                   "recovered_inbound_by_material": recovered},
        "evidence": {"source_reference": option["source_reference"], "geometry_source": "operator-supplied scenario input",
                     "expected_transit_source": "operator-supplied scenario input"},
        "limitations": ["The route geometry and transit estimate are scenario inputs and are not independently verified.",
                        "No traffic, border, carrier-capacity, or alternate-route service is connected."],
    }


def _combine_recovery_strategies(name, components, baseline_projections, recovered_projections):
    component_metrics = [item.get("metrics") or {} for item in components]
    recovery_days = [metric["recovery_days"] for metric in component_metrics if metric.get("recovery_days") is not None]
    priced = [metric for metric in component_metrics if metric.get("estimated_cost") is not None]
    currencies = {metric.get("currency") for metric in priced}
    total_cost = None
    currency = None
    cost_basis = None
    if priced and len(priced) == len(component_metrics) and len(currencies) == 1 and None not in currencies:
        total_cost = str(sum((_decimal(metric["estimated_cost"]) for metric in priced), Decimal("0")).quantize(Decimal("0.01")))
        currency = next(iter(currencies))
        bases = {metric.get("cost_basis") for metric in priced}
        cost_basis = next(iter(bases)) if len(bases) == 1 else "mixed"

    baseline_by_id = {row["material_id"]: row for row in baseline_projections}
    recovered_by_id = {row["material_id"]: row for row in recovered_projections}
    total_initial_gap = Decimal("0")
    total_remaining_gap = Decimal("0")
    known_gap_count = 0
    for material_id, baseline in baseline_by_id.items():
        if baseline["simulated"].get("projected_available") is None:
            continue
        before = _scenario_gap(baseline)
        if before <= 0:
            continue
        after = _scenario_gap(recovered_by_id[material_id])
        total_initial_gap += before
        total_remaining_gap += after
        known_gap_count += 1
    service_level = None
    if total_initial_gap > 0 and known_gap_count:
        service_level = float(min(Decimal("100"), max(Decimal("0"), (total_initial_gap - total_remaining_gap) / total_initial_gap * Decimal("100"))))
    risks = [metric["supplier_risk_score"] for metric in component_metrics if metric.get("supplier_risk_score") is not None]
    return {
        "id": f"operator-combination:{name}",
        "strategy_type": "recovery_combination",
        "name": f"Combined recovery · {name}",
        "status": "hypothetical",
        "metrics": {"recovery_days": max(recovery_days) if recovery_days else None,
                    "estimated_cost": total_cost, "currency": currency,
                    "cost_basis": cost_basis,
                    "service_level_percent": service_level,
                    "supplier_risk_score": max(risks) if risks else None},
        "result": {"components": [{"strategy_type": item["strategy_type"], "name": item["name"],
                                    "metrics": item.get("metrics"), "result": item.get("result"),
                                    "evidence": item.get("evidence"), "limitations": item.get("limitations")}
                                   for item in components],
                   "timing_assumption": "Components are assumed to run in parallel; recovery time is the slowest component."},
        "limitations": ["A combined option applies its components in the order supplied to the simulator.",
                        "Recovery time assumes parallel execution and reports the slowest component.",
                        "Combined cost is omitted unless every component has a supplied or supported estimate in the same currency."],
    }


def _apply_available_delta(projection, quantity):
    simulated = projection["simulated"]
    current = _decimal(simulated.get("projected_available"))
    if current is not None:
        simulated["projected_available"] = str(current + quantity)
        return
    supply_only = _decimal(simulated.get("supply_only_available"))
    if supply_only is not None:
        simulated["supply_only_available"] = str(supply_only + quantity)


def target_supplier_id(scenario):
    return scenario.get("entity_id") if scenario["scenario_type"] == "supplier_failure" else None
