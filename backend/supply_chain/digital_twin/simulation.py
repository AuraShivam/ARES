from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from supply_chain.models import (
    Inventory, InventoryMovement, Material, PurchaseOrder, Shipment, Supplier, Warehouse,
)
from .recovery import compare_recovery_options


INBOUND_STATUSES = ("approved", "in_transit", "delayed")


def _order_materials(order):
    lines = list(order.lines.select_related("material"))
    if lines:
        return [(line.material, line.quantity - line.received_quantity) for line in lines]
    return [(order.material, order.quantity)]


def _scheduled_inbound(order, horizon_end):
    if order.status not in INBOUND_STATUSES:
        return None, "Purchase order is not in an inbound operational status."
    if order.expected_date is not None:
        return (order.expected_date <= horizon_end, "purchase-order expected date")
    shipment = order.shipments.filter(status__in=["planned", "in_transit", "delayed", "at_risk"]).exclude(eta__isnull=True).order_by("eta").first()
    if shipment:
        return (shipment.eta <= horizon_end, "linked shipment ETA")
    return None, "Inbound date is missing; not included in quantified projections."


def _orders_for_materials(material_ids):
    if not material_ids:
        return []
    return list(PurchaseOrder.objects.filter(status__in=INBOUND_STATUSES).filter(
        Q(material_id__in=material_ids) | Q(lines__material_id__in=material_ids)
    ).distinct().prefetch_related("lines__material", "shipments"))


def _material_history(material_id, horizon_days):
    today = timezone.localdate()
    start = today - timedelta(days=89)
    movements = InventoryMovement.objects.filter(
        inventory__material_id=material_id,
        movement_type="issue",
        occurred_at__gte=start,
        occurred_at__lte=today,
    )
    aggregate = movements.aggregate(total=Sum("quantity_delta"))
    total = aggregate["total"] or Decimal("0")
    # occurred_at is a DateField, so distinct values are distinct calendar days.
    distinct_days = movements.values("occurred_at").distinct().count()
    first_day = movements.order_by("occurred_at").values_list("occurred_at", flat=True).first()
    ready = distinct_days >= 10 and first_day is not None and first_day <= today - timedelta(days=59)
    if not ready:
        return None, {"distinct_consumption_days": distinct_days, "history_start": first_day, "required_days": 10,
                      "required_history_span_days": 60}
    daily = abs(Decimal(total)) / Decimal("90")
    return daily * Decimal(horizon_days), {"distinct_consumption_days": distinct_days,
                                           "history_start": first_day,
                                           "average_daily_issue": str(daily)}


def _resolve_impacted_materials(scenario_type, entity_id, horizon_end):
    notes = []
    shipment_ids = set()
    po_ids = set()
    if scenario_type == "supplier_failure":
        supplier = Supplier.objects.get(pk=entity_id)
        failed_orders = list(PurchaseOrder.objects.filter(supplier=supplier, status__in=INBOUND_STATUSES).prefetch_related("lines__material"))
        impacted_material_ids = {material.pk for order in failed_orders for material, _qty in _order_materials(order)}
        orders = _orders_for_materials(impacted_material_ids)
        notes.append(f"Supplier {supplier.code} is assumed unable to fulfill open inbound orders in the selected horizon.")
        if not impacted_material_ids:
            notes.append("No open inbound purchase orders for this supplier were found.")
    elif scenario_type == "warehouse_failure":
        warehouse = Warehouse.objects.get(pk=entity_id)
        materials = set(Inventory.objects.filter(warehouse=warehouse).values_list("material_id", flat=True))
        shipments = list(Shipment.objects.filter(
            Q(destination__iexact=warehouse.name) | Q(destination__iexact=warehouse.code),
            status__in=["planned", "in_transit", "delayed", "at_risk"],
        ).select_related("purchase_order"))
        materials.update(material.pk for shipment in shipments for material, _qty in _order_materials(shipment.purchase_order))
        orders = _orders_for_materials(materials)
        shipment_ids.update(str(item.pk) for item in shipments)
        notes.append("On-hand balances at the selected warehouse are removed from the simulated available stock.")
        notes.append("Purchase-order destination is resolved only from an exact shipment destination/name match; unresolved inbound destinations are not attributed to this warehouse.")
        return list(Material.objects.filter(pk__in=materials)), orders, shipment_ids, notes, warehouse
    elif scenario_type in {"shipment_delay", "route_disruption"}:
        shipment = Shipment.objects.select_related("purchase_order").get(pk=entity_id)
        if shipment.status == "delivered":
            raise ValueError("A delivered shipment cannot be delayed in a what-if scenario.")
        shipment_ids.add(str(shipment.pk))
        materials = list({material.pk: material for material, _qty in _order_materials(shipment.purchase_order)}.values())
        orders = _orders_for_materials({material.pk for material in materials})
        notes.append("ARES links the shipment to a purchase order but does not allocate shipment quantities to PO lines.")
        if shipment.purchase_order.shipments.count() > 1:
            notes.append("Scenario assumes the selected shipment carries all open quantities on its purchase order; other linked shipments may share that quantity.")
        return materials, orders, shipment_ids, notes, shipment
    elif scenario_type in {"material_shortage", "demand_surge"}:
        material = Material.objects.get(pk=entity_id)
        orders = _orders_for_materials({material.pk})
        shipment_ids.update(str(shipment.pk) for order in orders for shipment in order.shipments.all())
        return [material], orders, shipment_ids, notes, material
    else:
        raise ValueError("Unsupported digital twin scenario type.")

    materials_by_id = {}
    for order in orders:
        po_ids.add(str(order.pk))
        for material, _quantity in _order_materials(order):
            materials_by_id[material.pk] = material
        shipment_ids.update(str(shipment.pk) for shipment in order.shipments.all())
    return list(materials_by_id.values()), orders, shipment_ids, notes, supplier


def execute_simulation(scenario):
    """Compute an isolated what-if result from a read-only operational snapshot."""
    scenario_type = scenario["scenario_type"]
    horizon_days = scenario["horizon_days"]
    horizon_end = timezone.localdate() + timedelta(days=horizon_days)
    materials, orders, shipment_ids, notes, target = _resolve_impacted_materials(
        scenario_type, scenario["entity_id"], horizon_end,
    )
    if scenario_type == "route_disruption":
        if not any(option.get("strategy_type") == "route_alternative" for option in scenario.get("recovery_options", [])):
            notes.append("No alternate route was supplied for this scenario; ARES does not invent routes or query a routing provider.")
        else:
            notes.append("Alternate route options are operator-supplied scenario assumptions and are not independently verified.")
    affected_po_ids = set()
    for order in orders:
        affected_po_ids.add(str(order.pk))
    inbound_by_material = {material.pk: Decimal("0") for material in materials}
    inbound_details = {material.pk: [] for material in materials}
    missing_dates = set()
    considered_orders = []
    delayed_order_ids = set()
    delayed_order_details = []
    for order in orders:
        if order.status not in INBOUND_STATUSES:
            continue
        if scenario_type in {"shipment_delay", "route_disruption"} and target and order.pk == target.purchase_order_id:
            due = target.eta or order.expected_date
            basis = "linked shipment ETA" if target.eta else "purchase-order expected date (shipment ETA unavailable)"
            included = due <= horizon_end if due else None
            if due:
                simulated_due = due + timedelta(days=scenario["delay_days"])
                if due <= horizon_end and simulated_due > horizon_end:
                    delayed_order_ids.add(order.pk)
                delayed_order_details.append({
                    "purchase_order": order.number,
                    "baseline_eta": due.isoformat(),
                    "simulated_eta": simulated_due.isoformat(),
                    "deferred_beyond_horizon": simulated_due > horizon_end,
                })
            else:
                missing_dates.add(order.number)
        else:
            included, basis = _scheduled_inbound(order, horizon_end)
        if included is None:
            missing_dates.add(order.number)
            continue
        if not included:
            continue
        considered_orders.append(order)
        for material, remaining in _order_materials(order):
            remaining = max(Decimal("0"), remaining)
            if material.pk in inbound_by_material:
                inbound_by_material[material.pk] += remaining
                inbound_details[material.pk].append({"purchase_order": order.number, "quantity": str(remaining), "date_basis": basis})

    projected = []
    for material in materials:
        inventory_rows = list(Inventory.objects.filter(material=material).select_related("warehouse"))
        on_hand = sum((record.quantity for record in inventory_rows), Decimal("0"))
        baseline_inbound = inbound_by_material.get(material.pk, Decimal("0"))
        baseline_demand, history = _material_history(material.pk, horizon_days)
        demand_is_known = baseline_demand is not None
        baseline_quantity = on_hand + baseline_inbound - (baseline_demand or Decimal("0"))
        simulated_quantity = baseline_quantity
        removed_stock = Decimal("0")
        removed_inbound = Decimal("0")
        if scenario_type == "supplier_failure" and target:
            selected_order_ids = {order.pk for order in orders if order.supplier_id == target.pk}
            removed_inbound = sum((qty for order in considered_orders if order.pk in selected_order_ids
                                   for item, qty in _order_materials(order) if item.pk == material.pk), Decimal("0"))
        elif scenario_type == "warehouse_failure" and target:
            removed_stock = sum((record.quantity for record in inventory_rows if record.warehouse_id == target.pk), Decimal("0"))
            destination_shipments = Shipment.objects.filter(
                purchase_order__in=orders,
            ).filter(
                Q(destination__iexact=target.name) | Q(destination__iexact=target.code),
            ).filter(
                status__in=["planned", "in_transit", "delayed", "at_risk"],
            ).select_related("purchase_order").prefetch_related("purchase_order__lines__material")
            target_order_ids = {shipment.purchase_order_id for shipment in destination_shipments}
            removed_inbound = sum((qty for order in considered_orders if order.pk in target_order_ids
                                   for item, qty in _order_materials(order) if item.pk == material.pk), Decimal("0"))
        elif scenario_type in {"shipment_delay", "route_disruption"} and target:
            selected_order_ids = delayed_order_ids
            removed_inbound = sum((qty for order in considered_orders if order.pk in selected_order_ids
                                   for item, qty in _order_materials(order) if item.pk == material.pk), Decimal("0"))
        elif scenario_type == "material_shortage":
            removed_stock = Decimal(scenario.get("shortage_quantity", "0"))
        elif scenario_type == "demand_surge" and demand_is_known:
            increase = Decimal(scenario.get("demand_increase_percent", "0")) / Decimal("100")
            simulated_quantity -= baseline_demand * increase

        simulated_quantity -= removed_stock + removed_inbound
        if scenario_type == "shipment_delay" or scenario_type == "route_disruption":
            notes.append(f"The selected shipment is shifted by {scenario['delay_days']} days. The result compares horizon-end quantities; intermediate day-by-day stockouts are not modeled.")
        if scenario_type == "demand_surge" and not demand_is_known:
            notes.append(f"Demand surge for {material.sku} cannot be quantified because verified movement history is below the 60-day/10-day readiness threshold.")
        unit = material.unit or "units"
        if demand_is_known and simulated_quantity < 0:
            consequence = f"Projected unmet quantity of {abs(simulated_quantity)} {unit} by the end of the selected horizon."
        elif demand_is_known and simulated_quantity < baseline_quantity:
            consequence = f"Projected availability is reduced by {baseline_quantity - simulated_quantity} {unit} versus baseline."
        elif not demand_is_known:
            consequence = "Consumption history is insufficient to quantify demand-adjusted availability."
        else:
            consequence = "No horizon-end availability change is quantified for this material."
        projected.append({
            "material_id": str(material.pk), "sku": material.sku, "name": material.name,
            "unit": unit, "consequence": consequence,
            "baseline": {"on_hand": str(on_hand), "inbound_within_horizon": str(baseline_inbound),
                         "expected_consumption": str(baseline_demand) if demand_is_known else None,
                         "projected_available": str(baseline_quantity) if demand_is_known else None,
                         "supply_only_available": str(on_hand + baseline_inbound) if not demand_is_known else None},
            "simulated": {"removed_on_hand": str(removed_stock), "deferred_inbound": str(removed_inbound),
                          "projected_available": str(simulated_quantity) if demand_is_known else None,
                          "supply_only_available": str(simulated_quantity) if not demand_is_known and scenario_type != "demand_surge" else None},
            "demand_history": {**history, "history_start": history["history_start"].isoformat() if history.get("history_start") else None},
            "inbound_orders": inbound_details.get(material.pk, []),
        })
    if missing_dates:
        notes.append("Some inbound orders have no expected date or linked shipment ETA and were excluded from quantified projections: " + ", ".join(sorted(missing_dates)[:20]) + ("…" if len(missing_dates) > 20 else ""))
    if not materials:
        notes.append("No materials could be connected to this scenario from current ARES records.")
    recovery_comparison = compare_recovery_options(
        scenario, target, materials, projected,
    )
    return {
        "label": "SIMULATED",
        "scenario": scenario,
        "horizon_end": horizon_end.isoformat(),
        "status": "insufficient_data" if scenario_type == "demand_surge" and projected and projected[0]["simulated"]["projected_available"] is None else "completed",
        "summary": {"affected_materials": len(projected), "purchase_orders_in_scope": len(affected_po_ids),
                    "shipments_in_scope": len(shipment_ids),
                    "orders_with_inbound_in_horizon": len(considered_orders)},
        "purchase_orders": sorted({order.number for order in orders}),
        "delayed_purchase_orders": delayed_order_details,
        "shipments": sorted(shipment_ids),
        "material_projection": projected,
        "recovery_comparison": recovery_comparison,
        "assumptions_and_data_gaps": list(dict.fromkeys(notes)),
        "production_records_changed": False,
    }
