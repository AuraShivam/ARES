"""Evidence-based, deterministic risk scoring for the ARES MVP."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Inventory, PurchaseOrder


SEVERITY_POINTS = {"low": 15, "medium": 35, "high": 60, "critical": 80}
STALE_SOURCE_DAYS = 90


def _related_purchase_orders(supplier, shipment):
    criteria = Q()
    if supplier:
        criteria |= Q(supplier_id=supplier.pk)
    if shipment:
        criteria |= Q(pk=shipment.purchase_order_id)
    if not criteria:
        return []
    return list(
        PurchaseOrder.objects.filter(criteria)
        .select_related("supplier", "material")
        .prefetch_related("lines__material")
    )


def _materials_for_orders(orders):
    materials = {}
    for order in orders:
        lines = list(order.lines.all())
        if lines:
            for line in lines:
                materials[line.material_id] = line.material
        elif order.material_id:
            # Compatibility for older purchase orders without normalized lines.
            materials[order.material_id] = order.material
    return list(materials.values())


def build_evidence(disruption, today=None):
    """Collect the supply-chain records directly linked to a disruption."""
    today = today or timezone.localdate()
    shipment = disruption.affected_shipment
    supplier = disruption.affected_supplier
    if supplier is None and shipment:
        supplier = shipment.purchase_order.supplier

    linked_orders = _related_purchase_orders(supplier, shipment)
    open_orders = [order for order in linked_orders if order.status not in {"received", "cancelled"}]
    delayed_orders = [order for order in open_orders if order.status == "delayed"]
    materials = _materials_for_orders(open_orders)
    inventory_rows = list(
        Inventory.objects.filter(material_id__in=[material.pk for material in materials])
        .select_related("material", "warehouse")
    ) if materials else []

    stock_by_material = {
        material.pk: {"quantity": 0, "reorder_point": 0, "inventory_records": 0}
        for material in materials
    }
    for inventory in inventory_rows:
        stock = stock_by_material[inventory.material_id]
        stock["quantity"] += inventory.quantity
        stock["reorder_point"] += inventory.reorder_point
        stock["inventory_records"] += 1

    material_evidence = [
        {
            "sku": material.sku,
            "criticality": material.criticality,
            **stock_by_material[material.pk],
        }
        for material in materials
    ]

    now = timezone.now()
    freshness = []
    if disruption.source_name:
        freshness.append((f"Disruption source {disruption.title}", disruption.source_updated_at))
    if supplier:
        freshness.append((f"Supplier {supplier.code}", supplier.source_updated_at))
    if shipment and shipment.source_name:
        freshness.append((f"Shipment {shipment.reference}", shipment.source_updated_at))
    freshness.extend((f"Purchase order {order.number}", order.source_updated_at) for order in open_orders)
    freshness.extend((f"Material {material.sku}", material.source_updated_at) for material in materials)
    freshness.extend(
        (f"Inventory {inventory.material.sku} at {inventory.location}", inventory.source_updated_at)
        for inventory in inventory_rows
    )
    stale_before = now - timedelta(days=STALE_SOURCE_DAYS)
    stale_sources = [label for label, timestamp in freshness if timestamp and timestamp < stale_before]
    freshness_unknown = sum(timestamp is None for _label, timestamp in freshness)

    region_anchors = []
    if supplier and supplier.region:
        region_anchors.append(f"supplier region: {supplier.region}")
    if shipment:
        if shipment.origin:
            region_anchors.append(f"shipment origin: {shipment.origin}")
        if shipment.destination:
            region_anchors.append(f"shipment destination: {shipment.destination}")
    region_anchors.extend(
        f"warehouse region: {inventory.warehouse.region}"
        for inventory in inventory_rows
        if inventory.warehouse and inventory.warehouse.region
    )

    return {
        "supplier": {
            "code": supplier.code,
            "risk_score": supplier.risk_score,
            "status": supplier.status,
            "lead_time_days": supplier.lead_time_days,
        } if supplier else None,
        "shipment": {
            "reference": shipment.reference,
            "risk_score": shipment.risk_score,
            "status": shipment.status,
            "overdue": bool(shipment.eta and shipment.eta < today and shipment.status != "delivered"),
        } if shipment else None,
        "purchase_orders": [
            {"number": order.number, "status": order.status}
            for order in open_orders
        ],
        "delayed_purchase_orders": len(delayed_orders),
        "materials": material_evidence,
        "stale_sources": stale_sources,
        "freshness_unknown": freshness_unknown,
        "region_anchors": region_anchors,
        "affected_region": disruption.affected_region,
    }


def _region_matches(affected_region, anchors):
    target = " ".join((affected_region or "").casefold().split())
    if len(target) < 3:
        return []
    matches = []
    for anchor in anchors:
        label, _, raw_value = anchor.partition(":")
        value = " ".join(raw_value.casefold().split())
        if value and (target == value or (len(value) >= 4 and (target in value or value in target))):
            matches.append(anchor)
    return list(dict.fromkeys(matches))


def score_evidence(severity, confidence, evidence, disruption_id=None):
    """Score a compact evidence snapshot; kept pure for repeatable evaluation."""
    breakdown = []
    factors = []

    def add(label, points, detail):
        if points <= 0:
            return
        breakdown.append({"label": label, "points": points, "detail": detail})
        factors.append(f"{label}: +{points} points — {detail}")

    base = SEVERITY_POINTS.get(severity, 25)
    add("Disruption severity", base, f"{severity} severity sets the base impact.")

    supplier = evidence.get("supplier")
    if supplier:
        profile_points = round(supplier["risk_score"] * 0.15)
        add("Supplier profile", profile_points,
            f"{supplier['code']} has a {supplier['risk_score']}/100 risk profile.")
        status_points = {"watch": 6, "blocked": 14}.get(supplier["status"], 0)
        add("Supplier status", status_points, f"Supplier status is {supplier['status']}.")
        extra_lead_weeks = max(0, (supplier["lead_time_days"] - 21) // 7)
        lead_time_points = min(6, extra_lead_weeks * 2)
        add("Supplier lead time", lead_time_points,
            f"Lead time is {supplier['lead_time_days']} days, above the 21-day reference.")

    shipment = evidence.get("shipment")
    if shipment:
        shipment_points = round(shipment["risk_score"] * 0.12) if shipment["status"] != "delivered" else 0
        add("Shipment exposure", shipment_points,
            f"Shipment {shipment['reference']} has a {shipment['risk_score']}/100 risk score and is not delivered.")
        status_points = 8 if shipment["status"] in {"delayed", "at_risk"} else 0
        add("Shipment status", status_points, f"Shipment status is {shipment['status']}.")
        add("Overdue shipment", 8 if shipment["overdue"] else 0,
            f"Shipment {shipment['reference']} is past its ETA and not delivered.")

    orders = evidence.get("purchase_orders", [])
    order_points = min(8, len(orders) * 2)
    add("Open-order exposure", order_points,
        f"{len(orders)} open purchase order(s) link to the affected supply chain.")
    delayed_order_count = evidence.get("delayed_purchase_orders", 0)
    add("Delayed purchase orders", min(6, delayed_order_count * 3),
        f"{delayed_order_count} linked purchase order(s) are delayed.")

    materials = evidence.get("materials", [])
    criticality_points = {"low": 0, "medium": 4, "high": 8}
    highest_criticality = max(
        (criticality_points.get(material["criticality"], 4) for material in materials),
        default=0,
    )
    highest_label = next(
        (material["criticality"] for material in materials
         if criticality_points.get(material["criticality"], 4) == highest_criticality),
        "low",
    )
    add("Material criticality", highest_criticality,
        f"Highest linked material criticality is {highest_label}.")

    low_stock = [
        material for material in materials
        if material["inventory_records"] and material["quantity"] <= material["reorder_point"]
    ]
    missing_inventory = [material for material in materials if not material["inventory_records"]]
    add("Low inventory", min(12, len(low_stock) * 4),
        f"{len(low_stock)} linked material(s) are at or below their combined reorder point.")
    add("Inventory evidence gap", min(6, len(missing_inventory) * 2),
        f"Inventory is not recorded for {len(missing_inventory)} linked material(s).")

    region_matches = _region_matches(evidence.get("affected_region", ""), evidence.get("region_anchors", []))
    add("Regional exposure", 6 if region_matches else 0,
        f"Affected region matches {', '.join(region_matches)}.")

    stale_sources = evidence.get("stale_sources", [])
    add("Stale source data", min(6, len(stale_sources) * 2),
        f"{len(stale_sources)} linked source record(s) have timestamps older than {STALE_SOURCE_DAYS} days.")

    confidence_adjustment = round((100 - confidence) * 0.1)
    add("Reported confidence", confidence_adjustment,
        f"Reported event confidence is {confidence}%; uncertainty contributes points.")

    uncapped_score = sum(item["points"] for item in breakdown)
    score = min(100, max(0, uncapped_score))
    if uncapped_score > 100:
        factors.append(f"Combined evidence totals {uncapped_score}; the final score is capped at 100.")
    band = "critical" if score >= 80 else "high" if score >= 60 else "moderate" if score >= 35 else "low"

    data_gaps = []
    if not supplier and not shipment:
        data_gaps.append("No supplier or shipment is linked directly to this disruption.")
    if not orders:
        data_gaps.append("No open purchase orders are linked to the affected supplier or shipment.")
    if missing_inventory:
        data_gaps.append(f"Inventory coverage is missing for {len(missing_inventory)} linked material(s).")
    if stale_sources:
        data_gaps.append(f"{len(stale_sources)} linked source record(s) are older than {STALE_SOURCE_DAYS} days.")
    if evidence.get("freshness_unknown", 0):
        data_gaps.append(f"Source timestamps are unavailable for {evidence['freshness_unknown']} linked record(s).")

    if score >= 80:
        recommendation = "Escalate immediately to the supply-chain response owner; assess alternate sources and expedite options before approving a change."
    elif score >= 60:
        recommendation = "Escalate to the supply-chain response owner and prepare a contingency for exposed orders before approving a change."
    elif score >= 40:
        recommendation = "Review exposed orders and inventory buffers; prepare a contingency option and monitor for changes."
    else:
        recommendation = "Continue monitoring and validate the event against another source before taking operational action."
    if data_gaps:
        recommendation += " Validate the listed data gaps before relying on this assessment."

    material_count = len(materials)
    covered_count = material_count - len(missing_inventory)
    evidence_summary = {
        "open_purchase_orders": len(orders),
        "delayed_purchase_orders": delayed_order_count,
        "affected_materials": material_count,
        "materials_below_reorder": len(low_stock),
        "materials_without_inventory": len(missing_inventory),
        "inventory_coverage_percent": round(covered_count * 100 / material_count) if material_count else None,
        "stale_source_records": len(stale_sources),
        "freshness_unknown_records": evidence.get("freshness_unknown", 0),
        "regional_matches": region_matches,
        "data_gaps": data_gaps,
    }
    return {
        "disruption_id": str(disruption_id) if disruption_id else None,
        "risk_score": score,
        "uncapped_score": uncapped_score,
        "risk_band": band,
        "confidence": confidence,
        "score_breakdown": breakdown,
        "factors": factors,
        "evidence": evidence_summary,
        "recommendation": recommendation,
        "governance": "Advisory only. A human must review and approve any operational action.",
        "model": "ARES transparent rules v2",
    }


def assess(disruption, today=None):
    evidence = build_evidence(disruption, today=today)
    return score_evidence(
        disruption.severity,
        disruption.confidence,
        evidence,
        disruption_id=disruption.id,
    )
