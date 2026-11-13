from collections import defaultdict
from decimal import Decimal
from urllib.parse import urlsplit

from django.db.models import F, Sum, DecimalField, ExpressionWrapper
from django.utils import timezone
from django.db.models import Q

from supply_chain.geospatial import normalize_geojson_geometry
from supply_chain.models import (
    Disruption, ExternalFeedEvent, Inventory, Material, PurchaseOrder,
    PurchaseOrderLine, Shipment, Supplier, Warehouse,
)


NODE_TYPES = ("supplier", "warehouse", "material", "purchase_order", "shipment", "disruption")


def _safe_gdacs_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold()
        return value if parsed.scheme.casefold() == "https" and (hostname == "gdacs.org" or hostname.endswith(".gdacs.org")) else ""
    except ValueError:
        return ""


def _coordinates(latitude, longitude, label="", source="record"):
    if latitude is None or longitude is None:
        return None
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"latitude": lat, "longitude": lon, "label": label, "source": source}


def _source_point(payload, label):
    point = payload.get("point") if isinstance(payload, dict) else None
    if isinstance(point, str) and "," in point:
        try:
            latitude, longitude = point.split(",", 1)
            value = _coordinates(latitude, longitude, label, "gdacs_source_point")
            if value:
                return value
        except (TypeError, ValueError):
            pass
    if isinstance(payload, dict):
        return _coordinates(payload.get("latitude"), payload.get("longitude"), label, "gdacs_source_point")
    return None


def _risk_level(value):
    if value in {"critical", "high", "blocked", "delayed", "at_risk", "inactive"}:
        return "critical"
    if value in {"watch", "medium"}:
        return "warning"
    if value in {"low", "active", "open", "in_transit", "planned", "delivered", "received", "approved", "draft", "resolved", "cancelled"}:
        return "normal"
    return "unknown"


def _base_node(entity_type, entity, name, status_value, locations=None, kpis=None, expected_location_count=None, **metadata):
    locations = [value for value in (locations or []) if value]
    primary = locations[0] if len(locations) == 1 else None
    geometry_available = isinstance(metadata.get("source_geometry"), dict) or isinstance(metadata.get("route_geometry"), dict)
    expected_location_count = len(locations) if expected_location_count is None else expected_location_count
    return {
        "id": f"{entity_type}:{entity.pk}",
        "entity_id": str(entity.pk),
        "type": entity_type,
        "name": str(name),
        "status": status_value,
        "location": primary,
        "locations": locations,
        "geographic_data_available": bool(locations) or geometry_available,
        "geographic_data_unavailable": not bool(locations) and not geometry_available,
        "geographic_data_incomplete": len(locations) < expected_location_count and not isinstance(metadata.get("route_geometry"), dict),
        "risk_level": _risk_level(status_value),
        "kpis": kpis or {},
        "metadata": metadata,
    }


def _po_items(order):
    lines = list(order.lines.select_related("material"))
    if lines:
        return [(line.material, line.quantity, line.received_quantity, line.pk) for line in lines]
    return [(order.material, order.quantity, Decimal("0"), None)]


def build_graph():
    """Build a graph snapshot from persisted ARES records, without synthetic entities."""
    nodes, edges = [], []
    node_ids = set()
    suppliers = list(Supplier.objects.all())
    warehouses = list(Warehouse.objects.all())
    materials = list(Material.objects.select_related("preferred_supplier").prefetch_related("inventory__warehouse"))
    orders = list(PurchaseOrder.objects.select_related("supplier", "material").prefetch_related("lines__material", "shipments"))
    shipments = list(Shipment.objects.select_related("purchase_order", "purchase_order__supplier"))
    disruptions = list(Disruption.objects.select_related("affected_supplier", "affected_shipment"))

    def add_node(node):
        if node["id"] not in node_ids:
            nodes.append(node)
            node_ids.add(node["id"])

    def add_edge(source, target, relation, status_value="normal", metadata=None):
        if source in node_ids and target in node_ids:
            edges.append({"id": f"{source}|{relation}|{target}", "source": source, "target": target,
                          "type": relation, "status": status_value, "metadata": metadata or {}})

    for supplier in suppliers:
        node = _base_node("supplier", supplier, supplier.name, supplier.status,
                          [_coordinates(supplier.latitude, supplier.longitude, supplier.name)],
                          {"risk_score": supplier.risk_score, "lead_time_days": supplier.lead_time_days},
                          expected_location_count=1,
                          code=supplier.code, country=supplier.country, region=supplier.region,
                          status_label=supplier.get_status_display())
        node["risk_level"] = "critical" if supplier.status == "blocked" or supplier.risk_score >= 70 else "warning" if supplier.status == "watch" or supplier.risk_score >= 40 else "normal"
        add_node(node)
    for warehouse in warehouses:
        add_node(_base_node("warehouse", warehouse, warehouse.name, "active" if warehouse.active else "inactive",
                            [_coordinates(warehouse.latitude, warehouse.longitude, warehouse.name)],
                            {"inventory_records": warehouse.inventory.count()}, expected_location_count=1, code=warehouse.code,
                            country=warehouse.country, region=warehouse.region, warehouse_type=warehouse.warehouse_type,
                            active=warehouse.active))
    for material in materials:
        inventory = list(material.inventory.select_related("warehouse"))
        material_locations = []
        if material.preferred_supplier_id:
            material_locations.append(_coordinates(material.preferred_supplier.latitude, material.preferred_supplier.longitude,
                                                   material.preferred_supplier.name, "preferred_supplier"))
        for record in inventory:
            if record.warehouse_id:
                material_locations.append(_coordinates(record.warehouse.latitude, record.warehouse.longitude,
                                                       record.warehouse.name, "inventory_warehouse"))
        material_locations = list({(item["latitude"], item["longitude"], item["source"]): item
                                   for item in material_locations if item}.values())
        on_hand = sum((item.quantity for item in inventory), Decimal("0"))
        below_reorder = any(item.below_reorder_point for item in inventory)
        status_value = "critical" if below_reorder and material.criticality == "high" else "warning" if below_reorder else material.criticality
        add_node(_base_node("material", material, f"{material.sku} · {material.name}", status_value,
                            material_locations,
                            {"on_hand_quantity": str(on_hand), "inventory_records": len(inventory),
                             "below_reorder_point": below_reorder},
                            expected_location_count=(1 if material.preferred_supplier_id else 0) + len(inventory),
                            sku=material.sku, category=material.category,
                            unit=material.unit, criticality=material.criticality,
                            preferred_supplier_id=str(material.preferred_supplier_id) if material.preferred_supplier_id else None))
    for order in orders:
        supplier_location = _coordinates(order.supplier.latitude, order.supplier.longitude, order.supplier.name, "supplier")
        items = _po_items(order)
        add_node(_base_node("purchase_order", order, order.number, order.status, [supplier_location],
                            {"line_count": len(items), "quantity": str(sum((item[1] for item in items), Decimal("0")))},
                            expected_location_count=1,
                            supplier_id=str(order.supplier_id), status_label=order.get_status_display(),
                            expected_date=order.expected_date.isoformat() if order.expected_date else None,
                            material_skus=[item[0].sku for item in items]))
    for shipment in shipments:
        locations = [
            _coordinates(shipment.origin_latitude, shipment.origin_longitude, shipment.origin, "shipment_origin"),
            _coordinates(shipment.destination_latitude, shipment.destination_longitude, shipment.destination, "shipment_destination"),
        ]
        route_geometry = shipment.route_geometry
        if route_geometry:
            try:
                route_geometry = normalize_geojson_geometry(
                    route_geometry, allowed_types={"LineString", "MultiLineString"}, max_positions=5_000,
                )
            except (TypeError, ValueError):
                route_geometry = None
        add_node(_base_node("shipment", shipment, shipment.reference, shipment.status, locations,
                            {"risk_score": shipment.risk_score, "eta": shipment.eta.isoformat() if shipment.eta else None},
                            expected_location_count=0 if route_geometry else 2,
                            purchase_order_number=shipment.purchase_order.number, origin=shipment.origin,
                            destination=shipment.destination, carrier=shipment.carrier,
                            route_geometry=route_geometry,
                            route_geometry_source=shipment.route_geometry_source if route_geometry else "",
                            route_coordinates=[[loc["latitude"], loc["longitude"]] for loc in locations if loc]))
    source_events = {}
    now = timezone.now()
    for event in ExternalFeedEvent.objects.filter(disruption__isnull=False).order_by("-issued_at", "-created_at"):
        source_events.setdefault(event.disruption_id, event)
    for disruption in disruptions:
        event = source_events.get(disruption.pk)
        event_active = bool(event and event.lifecycle == "active" and (event.expires_at is None or event.expires_at > now))
        event_lifecycle = "expired" if event and event.lifecycle == "active" and event.expires_at and event.expires_at <= now else event.lifecycle if event else "unavailable"
        gdacs_sourced = "gdacs" in (disruption.source_name or "").casefold()
        location = None if gdacs_sourced and not event_active else _coordinates(
            disruption.latitude, disruption.longitude, disruption.affected_region or disruption.title,
        )
        payload = event.payload if event and isinstance(event.payload, dict) else {}
        if location is None and event_active:
            location = _source_point(payload, disruption.affected_region or disruption.title)
        raw_geometry = payload.get("geometry") if event_active else None
        geometry = raw_geometry if isinstance(raw_geometry, dict) else None
        geometry_status = payload.get("geometry_status", "missing")
        if geometry:
            try:
                geometry = normalize_geojson_geometry(
                    geometry, allowed_types={"Point", "Polygon", "MultiPolygon"}, max_positions=20_000,
                )
            except (TypeError, ValueError):
                geometry = None
                geometry_status = "invalid"
        if geometry:
            geometry_status = "valid"
        node = _base_node("disruption", disruption, disruption.title, disruption.status,
                          [location], {"severity": disruption.severity, "confidence": disruption.confidence},
                          expected_location_count=(1 if not geometry else (1 if location else 0)),
                          disruption_type=disruption.disruption_type, affected_region=disruption.affected_region,
                          status_label=disruption.get_status_display(), source_name=disruption.source_name,
                          source_key=disruption.source_key, source_geometry=geometry,
                          source_event_active=event_active,
                          source_event_lifecycle=event_lifecycle,
                          source_event_id=str(event.pk) if event else None,
                          source_event_external_id=payload.get("event_id"),
                          source_event_episode_id=payload.get("episode_id"),
                          source_event_type=event.event_type if event else None,
                          source_event_title=event.title if event else None,
                          source_event_severity=event.severity if event else None,
                          source_event_issued_at=event.issued_at.isoformat() if event and event.issued_at else None,
                          source_event_effective_at=event.effective_at.isoformat() if event and event.effective_at else None,
                          source_event_expires_at=event.expires_at.isoformat() if event and event.expires_at else None,
                          source_event_metrics=(payload.get("source_metrics") if isinstance(payload.get("source_metrics"), dict) else {}),
                          source_geometry_status=geometry_status,
                          source_alert_level=payload.get("alert_level"),
                          source_event_url=_safe_gdacs_url(payload.get("link", "")))
        node["risk_level"] = "normal" if disruption.status == "resolved" else _risk_level(disruption.severity)
        add_node(node)

    for material in materials:
        if material.preferred_supplier_id:
            add_edge(f"supplier:{material.preferred_supplier_id}", f"material:{material.pk}", "supplies",
                     metadata={"basis": "preferred_supplier"})
    for order in orders:
        supplier_id = f"supplier:{order.supplier_id}"
        order_id = f"purchase_order:{order.pk}"
        add_edge(supplier_id, order_id, "supplies", status_value=order.status)
        for material, quantity, received, line_id in _po_items(order):
            add_edge(order_id, f"material:{material.pk}", "contains", status_value=order.status,
                     metadata={"quantity": str(quantity), "received_quantity": str(received),
                               "line_id": str(line_id) if line_id else None})
        for shipment in order.shipments.all():
            add_edge(order_id, f"shipment:{shipment.pk}", "transports", status_value=shipment.status)
    for record in Inventory.objects.select_related("material", "warehouse"):
        if record.warehouse_id:
            add_edge(f"material:{record.material_id}", f"warehouse:{record.warehouse_id}", "stores",
                     status_value="warning" if record.below_reorder_point else "normal",
                     metadata={"inventory_id": str(record.pk), "quantity": str(record.quantity),
                               "reorder_point": str(record.reorder_point), "unit_cost": str(record.unit_cost)})
    warehouse_lookup = defaultdict(list)
    for warehouse in warehouses:
        for key in (warehouse.name.strip().casefold(), warehouse.code.strip().casefold()):
            if key:
                warehouse_lookup[key].append(warehouse)
    for shipment in shipments:
        for endpoint, label in (("origin", shipment.origin), ("destination", shipment.destination)):
            matches = warehouse_lookup.get(label.strip().casefold(), [])
            if len(matches) == 1:
                add_edge(f"shipment:{shipment.pk}", f"warehouse:{matches[0].pk}", endpoint,
                         metadata={"resolution": "exact warehouse name/code"})
    for disruption in disruptions:
        disruption_id = f"disruption:{disruption.pk}"
        if disruption.affected_supplier_id:
            add_edge(disruption_id, f"supplier:{disruption.affected_supplier_id}", "affects",
                     status_value=disruption.severity, metadata={"basis": "explicit_record_link"})
        if disruption.affected_shipment_id:
            add_edge(disruption_id, f"shipment:{disruption.affected_shipment_id}", "affects",
                     status_value=disruption.severity, metadata={"basis": "explicit_record_link"})

    return {"nodes": nodes, "edges": edges, "generated_at": timezone.now()}


def filter_graph(graph, node_types=None, statuses=None, risk_levels=None, search=""):
    type_set = set(node_types or [])
    status_set = set(statuses or [])
    risk_set = set(risk_levels or [])
    query = (search or "").strip().casefold()
    nodes = [node for node in graph["nodes"]
             if (not type_set or node["type"] in type_set)
             and (not status_set or node["status"] in status_set)
             and (not risk_set or node["risk_level"] in risk_set)
             and (not query or query in node["name"].casefold() or query in node["id"].casefold())]
    return nodes


def health_kpis():
    inventory_value = Inventory.objects.aggregate(
        total=Sum(ExpressionWrapper(F("quantity") * F("unit_cost"), output_field=DecimalField(max_digits=24, decimal_places=2)))
    )["total"] or Decimal("0")
    return {
        "generated_at": timezone.now(),
        "suppliers_total": Supplier.objects.count(),
        "suppliers_active": Supplier.objects.filter(status="active").count(),
        "suppliers_high_risk": Supplier.objects.filter(Q(risk_score__gte=70) | Q(status__in=["watch", "blocked"])).count(),
        "warehouses_total": Warehouse.objects.count(),
        "warehouses_active": Warehouse.objects.filter(active=True).count(),
        "materials_total": Material.objects.count(),
        "inventory_value": str(inventory_value),
        "inventory_value_currency": "mixed_or_unspecified",
        "active_shipments": Shipment.objects.filter(status__in=["planned", "in_transit", "at_risk"]).count(),
        "delayed_shipments": Shipment.objects.filter(status="delayed").count(),
        "open_purchase_orders": PurchaseOrder.objects.exclude(status__in=["received", "cancelled"]).count(),
        "disrupted_facilities": Supplier.objects.filter(status="blocked").count() + Warehouse.objects.filter(active=False).count(),
        "potential_shortages": Inventory.objects.filter(quantity__lte=F("reorder_point")).values("material_id").distinct().count(),
        "geographic_data_unavailable": {
            "suppliers": Supplier.objects.filter(latitude__isnull=True).count(),
            "warehouses": Warehouse.objects.filter(latitude__isnull=True).count(),
            "shipments_without_any_endpoint": Shipment.objects.filter(origin_latitude__isnull=True, destination_latitude__isnull=True).count(),
        },
    }
