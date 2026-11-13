import json
from collections import defaultdict
from urllib.parse import urlsplit

from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from supply_chain.models import (
    DigitalTwinChangeEvent, DigitalTwinSimulation, Disruption, ExternalFeed, Material,
    PurchaseOrder, Shipment, Supplier, Warehouse,
)
from .graph import NODE_TYPES, build_graph, filter_graph, health_kpis
from .impact import _valid_source_geometry, analyze_disruption_impact
from .serializers import SimulationRequestSerializer
from .simulation import execute_simulation


PAGE_SIZE_DEFAULT = 100
PAGE_SIZE_MAX = 500
CHANGE_PAGE_MAX = 500
ENTITY_MODELS = {
    "supplier": Supplier,
    "warehouse": Warehouse,
    "material": Material,
    "purchase_order": PurchaseOrder,
    "shipment": Shipment,
    "disruption": Disruption,
}


def _safe_source_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold()
        return value if parsed.scheme.casefold() == "https" and (hostname == "gdacs.org" or hostname.endswith(".gdacs.org")) else ""
    except ValueError:
        return ""


def _csv_parameter(request, name, allowed=None):
    values = [part.strip() for part in request.query_params.get(name, "").split(",") if part.strip()]
    if allowed is not None:
        invalid = sorted(set(values) - set(allowed))
        if invalid:
            raise ValidationError({name: f"Unsupported value(s): {', '.join(invalid)}."})
    return values


def _page(request, values):
    try:
        page = int(request.query_params.get("page", "1"))
        size = int(request.query_params.get("page_size", str(PAGE_SIZE_DEFAULT)))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": "page and page_size must be positive integers."}) from exc
    if page < 1 or size < 1 or size > PAGE_SIZE_MAX:
        raise ValidationError({"page_size": f"page must be positive; page_size must be 1–{PAGE_SIZE_MAX}."})
    start = (page - 1) * size
    return values[start:start + size], {"count": len(values), "page": page, "page_size": size,
                                        "page_count": (len(values) + size - 1) // size}


def _filtered_nodes(request, graph):
    return filter_graph(
        graph,
        node_types=_csv_parameter(request, "type", NODE_TYPES),
        statuses=_csv_parameter(request, "status"),
        risk_levels=_csv_parameter(request, "risk_level", {"normal", "warning", "critical", "unknown"}),
        search=request.query_params.get("search", ""),
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def graph_snapshot(request):
    graph = build_graph()
    nodes = _filtered_nodes(request, graph)
    page_nodes, pagination = _page(request, nodes)
    visible = {node["id"] for node in page_nodes}
    all_ids = {node["id"] for node in graph["nodes"]}
    edges = [edge for edge in graph["edges"]
             if (edge["source"] in visible or edge["target"] in visible)
             and edge["source"] in all_ids and edge["target"] in all_ids]
    return Response({
        "generated_at": graph["generated_at"],
        "nodes": page_nodes,
        "edges": edges,
        "pagination": pagination,
        "graph_counts": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
                         "filtered_nodes": len(nodes), "page_edges": len(edges)},
        "edge_note": "Edges touching nodes on this page are included; the peer node may appear on another page. Use /edges/ for the complete separately paginated edge list.",
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def graph_nodes(request):
    graph = build_graph()
    nodes = _filtered_nodes(request, graph)
    page_nodes, pagination = _page(request, nodes)
    return Response({"results": page_nodes, "pagination": pagination, "generated_at": graph["generated_at"]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def graph_edges(request):
    graph = build_graph()
    node_ids = {node["id"] for node in _filtered_nodes(request, graph)}
    allowed_edges = {"supplies", "contains", "stores", "transports", "origin", "destination", "affects"}
    edge_types = _csv_parameter(request, "edge_type", allowed_edges)
    source, target = request.query_params.get("source"), request.query_params.get("target")
    edges = [edge for edge in graph["edges"]
             if (edge["source"] in node_ids or edge["target"] in node_ids)
             and (not edge_types or edge["type"] in edge_types)
             and (not source or edge["source"] == source)
             and (not target or edge["target"] == target)]
    page_edges, pagination = _page(request, edges)
    return Response({"results": page_edges, "pagination": pagination, "generated_at": graph["generated_at"]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def entity_detail(request, entity_type, entity_id):
    if entity_type not in ENTITY_MODELS:
        raise ValidationError({"entity_type": "Unsupported digital twin entity type."})
    graph = build_graph()
    node_id = f"{entity_type}:{entity_id}"
    node = next((candidate for candidate in graph["nodes"] if candidate["id"] == node_id), None)
    if node is None:
        get_object_or_404(ENTITY_MODELS[entity_type], pk=entity_id)
        raise ValidationError({"entity_id": "The entity is not represented in the digital twin graph."})
    related_edges = [edge for edge in graph["edges"] if edge["source"] == node_id or edge["target"] == node_id]
    related_ids = {edge["source"] for edge in related_edges} | {edge["target"] for edge in related_edges}
    related_nodes = [candidate for candidate in graph["nodes"] if candidate["id"] in related_ids and candidate["id"] != node_id]
    return Response({"entity": node, "relationships": related_edges, "related_entities": related_nodes})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def geo_data(request):
    graph = build_graph()
    features = []
    missing = defaultdict(int)
    for node in graph["nodes"]:
        if node["type"] == "disruption":
            if node["status"] == "resolved":
                continue
            source_name = (node.get("metadata") or {}).get("source_name", "").casefold()
            if "gdacs" in source_name and not (node.get("metadata") or {}).get("source_event_active"):
                continue
        if node["type"] == "shipment":
            route_geometry = node["metadata"].get("route_geometry")
            if route_geometry:
                features.append({"type": "Feature", "id": node["id"], "geometry": route_geometry,
                                 "properties": {"id": node["id"], "type": node["type"], "name": node["name"],
                                                "status": node["status"],
                                                "route_display": "supplied shipment route geometry; source attribution recorded",
                                                "route_geometry_source": node["metadata"].get("route_geometry_source") or "not specified"}})
            coords = node["metadata"].get("route_coordinates") or []
            if not route_geometry and len(coords) == 2:
                geometry = {"type": "LineString", "coordinates": [[coords[0][1], coords[0][0]], [coords[1][1], coords[1][0]]]}
                features.append({"type": "Feature", "id": node["id"], "geometry": geometry,
                                 "properties": {"id": node["id"], "type": node["type"], "name": node["name"], "status": node["status"],
                                                "route_display": "direct line between recorded endpoints; not carrier route geometry"}})
            elif not route_geometry:
                missing["shipments"] += 1
            for index, location in enumerate(node["locations"]):
                features.append({"type": "Feature", "id": f"{node['id']}:endpoint:{index}", "geometry": {
                    "type": "Point", "coordinates": [location["longitude"], location["latitude"]]},
                    "properties": {"id": node["id"], "type": "shipment_endpoint", "name": location["label"],
                                   "shipment": node["name"], "status": node["status"]}})
            continue
        metadata = node.get("metadata") or {}
        geometry = metadata.get("source_geometry") if node["type"] == "disruption" else None
        if geometry and not _valid_source_geometry(geometry):
            geometry = None
        if not geometry and node.get("location"):
            point = node["location"]
            geometry = {"type": "Point", "coordinates": [point["longitude"], point["latitude"]]}
        if geometry:
            features.append({"type": "Feature", "id": node["id"], "geometry": geometry,
                             "properties": {"id": node["id"], "type": node["type"], "name": node["name"],
                                            "status": node["status"], "risk_level": node["risk_level"],
                                            "source_name": metadata.get("source_name", ""),
                                            "source_event_id": metadata.get("source_event_id"),
                                            "source_event_external_id": metadata.get("source_event_external_id"),
                                            "source_event_episode_id": metadata.get("source_event_episode_id"),
                                            "source_event_type": metadata.get("source_event_type"),
                                            "source_alert_level": metadata.get("source_alert_level"),
                                            "source_event_lifecycle": metadata.get("source_event_lifecycle"),
                                            "source_event_issued_at": metadata.get("source_event_issued_at"),
                                            "source_event_effective_at": metadata.get("source_event_effective_at"),
                                            "source_event_expires_at": metadata.get("source_event_expires_at"),
                                            "source_geometry_status": metadata.get("source_geometry_status"),
                                            "source_event_metrics": metadata.get("source_event_metrics", {}),
                                            "source_url": _safe_source_url(metadata.get("source_event_url", ""))}})
        elif node["type"] in {"supplier", "warehouse", "disruption"}:
            missing[f"{node['type']}s"] += 1
        for index, location in enumerate(node.get("locations") or []):
            if node["type"] in {"supplier", "warehouse", "material"}:
                features.append({"type": "Feature", "id": f"{node['id']}:location:{index}", "geometry": {
                    "type": "Point", "coordinates": [location["longitude"], location["latitude"]]},
                    "properties": {"id": node["id"], "type": node["type"], "name": node["name"],
                                   "location_source": location["source"], "risk_level": node["risk_level"]}})
    return Response({"type": "FeatureCollection", "features": features,
                     "counts": {"features": len(features), "geographic_data_unavailable": dict(missing)},
                     "generated_at": graph["generated_at"]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health_overview(request):
    return Response(health_kpis())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def disruption_impact(request, disruption_id):
    try:
        return Response(analyze_disruption_impact(disruption_id))
    except Disruption.DoesNotExist as exc:
        raise ValidationError({"disruption_id": "Disruption not found."}) from exc
    except (TypeError, DjangoValidationError) as exc:
        raise ValidationError({"disruption_id": "Provide a valid disruption UUID."}) from exc


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def affected_dependencies(request, entity_type, entity_id):
    if entity_type not in ENTITY_MODELS:
        raise ValidationError({"entity_type": "Unsupported digital twin entity type."})
    graph = build_graph()
    node_id = f"{entity_type}:{entity_id}"
    nodes = {node["id"]: node for node in graph["nodes"]}
    if node_id not in nodes:
        raise ValidationError({"entity_id": "Entity not found."})
    direction = request.query_params.get("direction", "all")
    if direction not in {"upstream", "downstream", "all"}:
        raise ValidationError({"direction": "Use upstream, downstream, or all."})
    edges = [edge for edge in graph["edges"] if (direction in {"all", "upstream"} and edge["target"] == node_id)
             or (direction in {"all", "downstream"} and edge["source"] == node_id)]
    neighbor_ids = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
    neighbors = [nodes[value] for value in neighbor_ids if value in nodes and value != node_id]
    return Response({"entity": nodes[node_id], "direction": direction, "relationships": edges, "dependencies": neighbors})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sync_status(request):
    latest = DigitalTwinChangeEvent.objects.order_by("-sequence").first()
    pending = DigitalTwinChangeEvent.objects.filter(published_at__isnull=True)
    sources = list(ExternalFeed.objects.order_by("name").values(
        "key", "name", "enabled", "status", "last_attempt_at", "last_success_at",
        "events_seen", "events_created", "events_updated", "events_unchanged",
    ))
    return Response({"latest_sequence": latest.sequence if latest else 0,
                     "last_change_at": latest.created_at if latest else None,
                     "last_published_at": DigitalTwinChangeEvent.objects.exclude(published_at__isnull=True).order_by("-published_at").values_list("published_at", flat=True).first(),
                     "pending_delivery_count": pending.count(),
                     "sources": sources,
                     "recovery_endpoint": "/api/digital-twin/changes/?since=<sequence>"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def changes_since(request):
    try:
        since = int(request.query_params.get("since", "0"))
        limit = int(request.query_params.get("limit", "100"))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"since": "since and limit must be nonnegative/positive integers."}) from exc
    if since < 0 or limit < 1 or limit > CHANGE_PAGE_MAX:
        raise ValidationError({"since": f"since must be nonnegative and limit must be 1–{CHANGE_PAGE_MAX}."})
    query = DigitalTwinChangeEvent.objects.filter(sequence__gt=since).order_by("sequence")
    events = list(query[:limit])
    latest = DigitalTwinChangeEvent.objects.order_by("-sequence").values_list("sequence", flat=True).first() or 0
    return Response({"results": [{"sequence": item.sequence, "resource": item.resource,
                                  "entity_id": item.entity_id, "action": item.action,
                                  "created_at": item.created_at} for item in events],
                     "since": since, "next_since": events[-1].sequence if events else since,
                     "latest_sequence": latest, "has_more": bool(events and events[-1].sequence < latest)})


def _simulation_queryset(request):
    query = DigitalTwinSimulation.objects.select_related("requested_by")
    if not (request.user.is_staff or request.user.is_superuser):
        query = query.filter(requested_by=request.user)
    return query


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def simulations(request):
    if request.method == "GET":
        rows = _simulation_queryset(request)
        count = rows.count()
        try:
            page = int(request.query_params.get("page", "1"))
            size = int(request.query_params.get("page_size", str(PAGE_SIZE_DEFAULT)))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"page": "page and page_size must be positive integers."}) from exc
        if page < 1 or size < 1 or size > PAGE_SIZE_MAX:
            raise ValidationError({"page_size": f"page must be positive; page_size must be 1–{PAGE_SIZE_MAX}."})
        page_rows = rows[(page - 1) * size:page * size]
        pagination = {"count": count, "page": page, "page_size": size,
                      "page_count": (count + size - 1) // size}
        return Response({"results": [{"id": row.pk, "created_at": row.created_at,
                                      "scenario": row.scenario, "result": row.result} for row in page_rows],
                         "pagination": pagination})
    serializer = SimulationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    scenario = json.loads(json.dumps(serializer.validated_data, cls=DjangoJSONEncoder))
    model_by_scenario = {
        "supplier_failure": Supplier,
        "warehouse_failure": Warehouse,
        "shipment_delay": Shipment,
        "route_disruption": Shipment,
        "material_shortage": Material,
        "demand_surge": Material,
    }
    target_model = model_by_scenario[scenario["scenario_type"]]
    if not target_model.objects.filter(pk=scenario["entity_id"]).exists():
        raise ValidationError({"entity_id": "The selected entity does not exist."})
    try:
        result = execute_simulation(scenario)
    except (KeyError, ValueError) as exc:
        raise ValidationError({"scenario": str(exc)}) from exc
    row = DigitalTwinSimulation.objects.create(requested_by=request.user, scenario=scenario, result=result)
    return Response({"id": row.pk, "created_at": row.created_at, "scenario": row.scenario,
                     "result": row.result}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def simulation_detail(request, simulation_id):
    row = get_object_or_404(_simulation_queryset(request), pk=simulation_id)
    return Response({"id": row.pk, "created_at": row.created_at, "scenario": row.scenario, "result": row.result})
