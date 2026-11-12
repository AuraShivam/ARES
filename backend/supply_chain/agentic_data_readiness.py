"""Read-only data coverage report for planned agent and predictive capabilities."""

from datetime import timedelta

from django.db.models import Count, Min, Q
from django.utils import timezone

from .demand_forecast import MIN_HISTORY_DAYS, MIN_ISSUE_DAYS, LOOKBACK_DAYS
from .gdacs_feed import FEED_KEY
from .agents.providers import provider_readiness
from .models import (
    Disruption,
    ExternalFeed,
    ExternalFeedEvent,
    Inventory,
    InventoryMovement,
    Material,
    PurchaseOrder,
    PurchaseOrderLine,
    Shipment,
    Supplier,
    Warehouse,
)
from .predictive_risk import MIN_ROWS_PER_CLASS, MIN_TRAINING_ROWS, MIN_LATE_ROWS_FOR_DURATION


def _coverage_status(ready, available):
    if ready:
        return "ready"
    if available:
        return "limited"
    return "blocked"


def build_agent_data_readiness(today=None):
    """Summarize persisted evidence and known data gaps without inventing values."""
    today = today or timezone.localdate()
    history_start = today - timedelta(days=LOOKBACK_DAYS - 1)

    suppliers = Supplier.objects.count()
    materials = Material.objects.count()
    warehouses = Warehouse.objects.count()
    inventory_records = Inventory.objects.count()
    movements = InventoryMovement.objects.count()
    purchase_orders = PurchaseOrder.objects.count()
    purchase_order_lines = PurchaseOrderLine.objects.count()
    shipments = Shipment.objects.count()
    disruptions = Disruption.objects.count()

    issue_profiles = InventoryMovement.objects.filter(
        movement_type="issue",
        occurred_at__gte=history_start,
        occurred_at__lte=today,
    ).values("inventory__material_id").annotate(
        issue_days=Count("occurred_at", distinct=True),
        first_issue=Min("occurred_at"),
    )
    forecast_ready_materials = 0
    materials_with_history = 0
    for row in issue_profiles:
        coverage_days = (today - row["first_issue"]).days + 1
        issue_days = row["issue_days"]
        materials_with_history += 1
        if coverage_days >= MIN_HISTORY_DAYS and issue_days >= MIN_ISSUE_DAYS:
            forecast_ready_materials += 1

    verified = list(Shipment.objects.filter(
        delivery_outcome_verified=True,
        status="delivered",
        eta__isnull=False,
        actual_delivery_date__isnull=False,
    ).select_related("purchase_order").order_by("actual_delivery_date", "eta", "reference"))
    eligible_verified = []
    inconsistent_verified = 0
    for shipment in verified:
        order = shipment.purchase_order
        order_date = order.ordered_at or (order.created_at.date() if order.created_at else shipment.created_at.date())
        if shipment.eta < order_date or shipment.actual_delivery_date < order_date:
            inconsistent_verified += 1
            continue
        eligible_verified.append(shipment)
    late_deliveries = sum(item.actual_delivery_date > item.eta for item in eligible_verified)
    on_time_deliveries = len(eligible_verified) - late_deliveries
    shipment_model_ready = (
        len(eligible_verified) >= MIN_TRAINING_ROWS
        and late_deliveries >= MIN_ROWS_PER_CLASS
        and on_time_deliveries >= MIN_ROWS_PER_CLASS
    )

    supplier_ids_with_history = {item.purchase_order.supplier_id for item in eligible_verified}
    material_supplier_count = Material.objects.filter(preferred_supplier__isnull=False).count()
    materials_without_preferred_supplier = materials - material_supplier_count
    open_purchase_orders = PurchaseOrder.objects.filter(
        status__in=("approved", "in_transit", "delayed")
    ).count()
    active_shipments = Shipment.objects.filter(
        status__in=("planned", "in_transit", "delayed", "at_risk")
    )

    source_tracked_models = (
        Supplier, Material, Warehouse, Inventory, InventoryMovement,
        PurchaseOrder, Shipment, Disruption,
    )
    source_tracked_total = sum(model.objects.count() for model in source_tracked_models)
    records_with_source = sum(
        model.objects.exclude(source_name="").count() for model in source_tracked_models
    )

    feed = ExternalFeed.objects.filter(key=FEED_KEY).first()
    active_feed_events = 0
    # Expired-event filtering is datetime-based; retain alerts without an expiry.
    if feed:
        now = timezone.now()
        active_feed_events = ExternalFeedEvent.objects.filter(
            feed=feed,
            lifecycle="active",
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now)).count()

    supplier_coordinates = Supplier.objects.filter(latitude__isnull=False, longitude__isnull=False).count()
    warehouse_coordinates = Warehouse.objects.filter(latitude__isnull=False, longitude__isnull=False).count()
    shipment_endpoint_pairs = Shipment.objects.filter(
        origin_latitude__isnull=False,
        origin_longitude__isnull=False,
        destination_latitude__isnull=False,
        destination_longitude__isnull=False,
    ).count()
    active_disruptions = Disruption.objects.exclude(status="resolved").count()
    materials_with_inventory = Inventory.objects.values("material_id").distinct().count()

    forecast_ready = materials > 0 and forecast_ready_materials == materials
    risk_model_ready = shipment_model_ready
    gdacs_ready = bool(feed and feed.status == "ok")
    supplier_available = suppliers > 0
    logistics_available = shipments > 0
    procurement_available = open_purchase_orders > 0
    provider = provider_readiness()
    agent_runtime_configured = provider["status"] == "configured"

    return {
        "generated_at": timezone.now(),
        "as_of_date": today,
        "scope": "Counts and coverage are computed from current ARES PostgreSQL records; they do not certify external truth.",
        "entities": {
            "suppliers": suppliers,
            "materials": materials,
            "warehouses": warehouses,
            "inventory_records": inventory_records,
            "inventory_movements": movements,
            "purchase_orders": purchase_orders,
            "purchase_order_lines": purchase_order_lines,
            "shipments": shipments,
            "disruptions": disruptions,
        },
        "capabilities": {
            "deterministic_risk_assessment": {
                "status": "ready" if active_disruptions else "limited",
                "implementation": "available",
                "evidence": {"open_disruptions": active_disruptions, "all_disruptions": disruptions},
                "limitations": ["Rule-based scores are advisory and use only recorded evidence."],
            },
            "demand_forecasting": {
                "status": _coverage_status(forecast_ready, forecast_ready_materials > 0),
                "implementation": "experimental_model_available",
                "evidence": {
                    "materials_total": materials,
                    "materials_with_issue_history": materials_with_history,
                    "materials_meeting_history_threshold": forecast_ready_materials,
                    "minimum_history_days": MIN_HISTORY_DAYS,
                    "minimum_distinct_issue_days": MIN_ISSUE_DAYS,
                    "lookback_days": LOOKBACK_DAYS,
                    "issue_movements_in_lookback": InventoryMovement.objects.filter(
                        movement_type="issue", occurred_at__gte=history_start, occurred_at__lte=today
                    ).count(),
                },
                "limitations": ["Forecasts are withheld per material until both history thresholds are met; no accuracy claim is made."],
            },
            "shipment_delay_prediction": {
                "status": "ready" if risk_model_ready else "limited" if eligible_verified else "blocked",
                "implementation": "experimental_model_available",
                "evidence": {
                    "verified_eligible_deliveries": len(eligible_verified),
                    "late_deliveries": late_deliveries,
                    "on_time_deliveries": on_time_deliveries,
                    "inconsistent_verified_records_excluded": inconsistent_verified,
                    "minimum_total": MIN_TRAINING_ROWS,
                    "minimum_per_class": MIN_ROWS_PER_CLASS,
                    "duration_model_minimum_late_deliveries": MIN_LATE_ROWS_FOR_DURATION,
                    "duration_model_ready": late_deliveries >= MIN_LATE_ROWS_FOR_DURATION,
                },
                "limitations": ["Only approver-verified delivered outcomes count; probabilities are experimental and not independently calibrated."],
            },
            "supplier_intelligence": {
                "status": "limited" if supplier_available else "blocked",
                "implementation": "partial_data_only",
                "evidence": {
                    "suppliers": suppliers,
                    "suppliers_with_verified_delivery_history": len(supplier_ids_with_history),
                    "materials_with_preferred_supplier": material_supplier_count,
                    "materials_without_preferred_supplier": materials_without_preferred_supplier,
                    "qualified_supplier_material_pairs": None,
                    "supplier_capacity_records": None,
                },
                "limitations": ["ARES stores preferred suppliers but not a qualified alternative-supplier catalog, material capacity, or supplier quote catalog."],
            },
            "inventory_intelligence": {
                "status": "ready" if inventory_records and materials > 0 and materials_with_inventory == materials and forecast_ready_materials == materials else "limited" if inventory_records else "blocked",
                "implementation": "current_balances_available_forecasts_data_dependent",
                "evidence": {
                    "inventory_records": inventory_records,
                    "materials_with_inventory": materials_with_inventory,
                    "materials_with_forecast_history": materials_with_history,
                    "materials_with_forecast_ready_history": forecast_ready_materials,
                    "dated_issue_history_window_start": history_start,
                },
                "limitations": ["A current stock balance alone does not establish historical demand."],
            },
            "logistics_intelligence": {
                "status": "limited" if logistics_available else "blocked",
                "implementation": "shipment_records_available_route_optimization_unavailable",
                "evidence": {
                    "shipments": shipments,
                    "active_shipments": active_shipments.count(),
                    "active_shipments_with_eta": active_shipments.filter(eta__isnull=False).count(),
                    "shipments_with_both_endpoint_coordinates": shipment_endpoint_pairs,
                    "verified_route_geometry_records": None,
                    "route_alternatives_available": False,
                },
                "limitations": ["No carrier tracking feed, verified route geometry, live traffic, or route alternative provider is modeled."],
            },
            "procurement_intelligence": {
                "status": "limited" if procurement_available else "blocked",
                "implementation": "purchase_order_records_available",
                "evidence": {
                    "purchase_orders": purchase_orders,
                    "active_purchase_orders": open_purchase_orders,
                    "purchase_order_lines": purchase_order_lines,
                    "materials_without_preferred_supplier": materials_without_preferred_supplier,
                },
                "limitations": ["Recorded purchase prices are historical order values, not current alternative-supplier quotes."],
            },
            "disaster_intelligence": {
                "status": "ready" if gdacs_ready else "limited" if feed else "blocked",
                "implementation": "gdacs_connector_available",
                "evidence": {
                    "feed_status": feed.status if feed else "never",
                    "last_success_at": feed.last_success_at if feed else None,
                    "active_feed_events": active_feed_events,
                    "disruptions": disruptions,
                    "suppliers_with_coordinates": supplier_coordinates,
                    "warehouses_with_coordinates": warehouse_coordinates,
                },
                "limitations": ["A GDACS alert or geographic proximity is contextual evidence and does not prove operational impact."],
            },
            "agent_runtime": {
                "status": "configured" if agent_runtime_configured else "unavailable",
                "implementation": "single_agent_runtime_available",
                "evidence": {
                    "provider": provider["provider"],
                    "model": provider["model"],
                    "missing_configuration": provider["missing_configuration"],
                },
                "limitations": [
                    "Configuration status does not verify provider network reachability." if agent_runtime_configured else "The runtime will not execute until provider configuration and external-processing opt-in are complete.",
                    "Specialist workflows and multi-agent orchestration are Phase 3 work.",
                ],
            },
        },
        "data_quality": {
            "records_with_source_provenance": records_with_source,
            "source_tracked_records": source_tracked_total,
            "records_without_source_provenance": source_tracked_total - records_with_source,
            "materials_without_preferred_supplier": materials_without_preferred_supplier,
            "inventory_records_without_warehouse": Inventory.objects.filter(warehouse__isnull=True).count(),
            "shipments_without_eta": Shipment.objects.filter(eta__isnull=True).count(),
            "shipments_without_complete_endpoints": shipments - shipment_endpoint_pairs,
            "open_disruptions_without_linked_supplier_or_shipment": Disruption.objects.exclude(status="resolved").filter(
                affected_supplier__isnull=True, affected_shipment__isnull=True
            ).count(),
        },
        "source_freshness": [{
            "key": FEED_KEY,
            "name": feed.name if feed else "GDACS recent disasters",
            "status": feed.status if feed else "never",
            "enabled": feed.enabled if feed else False,
            "last_attempt_at": feed.last_attempt_at if feed else None,
            "last_success_at": feed.last_success_at if feed else None,
            "consecutive_failures": feed.consecutive_failures if feed else 0,
            "events_seen_last_sync": feed.events_seen if feed else 0,
        }],
        "data_model_gaps": [
            "Qualified supplier-to-material capability, capacity, contract, and current quote records are not modeled.",
            "Verified shipment route geometry and live carrier tracking are not available.",
            "Customer/order demand and production schedules are not represented as dedicated entities.",
            "Only approver-verified shipment outcomes and dated inventory issue movements are eligible training evidence.",
        ],
    }
