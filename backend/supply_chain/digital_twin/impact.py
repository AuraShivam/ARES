import math
from collections import defaultdict, deque

from django.conf import settings
from django.shortcuts import get_object_or_404

from supply_chain.models import Disruption
from .graph import build_graph


CLASSIFICATIONS = ("confirmed_affected", "geographically_exposed", "potentially_impacted", "unaffected", "insufficient_information")
EARTH_RADIUS_KM = 6371.0088


def _haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    delta_p = math.radians(lat2 - lat1)
    delta_l = math.radians(lon2 - lon1)
    value = math.sin(delta_p / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(delta_l / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1, math.sqrt(value)))


def _rings(geometry):
    if not isinstance(geometry, dict):
        return []
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon" and isinstance(coordinates, list):
        return [ring for ring in coordinates if isinstance(ring, list)]
    if kind == "MultiPolygon" and isinstance(coordinates, list):
        return [ring for polygon in coordinates if isinstance(polygon, list)
                for ring in polygon if isinstance(ring, list)]
    return []


def _valid_source_geometry(geometry):
    if not isinstance(geometry, dict):
        return False
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point":
        rings = [[[coordinates[0], coordinates[1]]]] if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2 else []
    elif kind in {"Polygon", "MultiPolygon"}:
        rings = _rings(geometry)
    else:
        return False
    if not rings:
        return False
    try:
        for ring in rings:
            if kind != "Point" and len(ring) < 4:
                return False
            for pair in ring:
                lon, lat = float(pair[0]), float(pair[1])
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    return False
    except (TypeError, ValueError, IndexError, OverflowError):
        return False
    return True


def _point_in_ring(lat, lon, ring):
    inside = False
    try:
        points = [(float(pair[1]), float(pair[0])) for pair in ring if isinstance(pair, (list, tuple)) and len(pair) >= 2]
    except (TypeError, ValueError, OverflowError):
        return False
    if any(not (-90 <= point_lat <= 90 and -180 <= point_lon <= 180) for point_lat, point_lon in points):
        return False
    if len(points) < 3:
        return False
    previous = points[-1]
    for current in points:
        y1, x1 = previous
        y2, x2 = current
        crosses = ((y1 > lat) != (y2 > lat)) and (lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-15) + x1)
        if crosses:
            inside = not inside
        previous = current
    return inside


def _inside_geometry(lat, lon, geometry):
    rings = _rings(geometry)
    if not rings:
        return False
    # GeoJSON Polygon rings are ordered exterior first, then holes.
    if geometry.get("type") == "Polygon":
        return _point_in_ring(lat, lon, rings[0]) and not any(_point_in_ring(lat, lon, ring) for ring in rings[1:])
    coordinates = geometry.get("coordinates") or []
    for polygon in coordinates:
        if not isinstance(polygon, list) or not polygon:
            continue
        if _point_in_ring(lat, lon, polygon[0]) and not any(_point_in_ring(lat, lon, ring) for ring in polygon[1:]):
            return True
    return False


def _distance_to_ring_km(lat, lon, ring):
    try:
        points = [(float(pair[1]), float(pair[0])) for pair in ring if isinstance(pair, (list, tuple)) and len(pair) >= 2]
    except (TypeError, ValueError, OverflowError):
        return float("inf")
    if any(not (-90 <= point_lat <= 90 and -180 <= point_lon <= 180) for point_lat, point_lon in points):
        return float("inf")
    if len(points) < 2:
        return float("inf")
    # Local equirectangular projection is adequate for the configured near-event distances.
    scale_x = math.cos(math.radians(lat))
    px, py = lon * scale_x, lat
    best = float("inf")
    for index, (y1, x1) in enumerate(points):
        y2, x2 = points[(index + 1) % len(points)]
        ax, ay, bx, by = x1 * scale_x, y1, x2 * scale_x, y2
        dx, dy = bx - ax, by - ay
        ratio = 0 if dx == 0 and dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        nearest_x, nearest_y = ax + ratio * dx, ay + ratio * dy
        best = min(best, math.hypot(px - nearest_x, py - nearest_y) * 111.195)
    return best


def _distance_to_geometry_km(lat, lon, geometry):
    return min((_distance_to_ring_km(lat, lon, ring) for ring in _rings(geometry)), default=float("inf"))


def _threshold(disruption):
    configured = getattr(settings, "ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM", {})
    # The configured shape is hazard type -> severity; default is the fallback policy.
    kind = (disruption.disruption_type or "").strip().casefold()
    type_values = configured.get(kind, {}) if isinstance(configured.get(kind), dict) else {}
    fallback = configured.get("default", {}) if isinstance(configured.get("default"), dict) else {}
    value = type_values.get(disruption.severity, fallback.get(disruption.severity, 0))
    return float(value), kind or "default"


def _source_geometry(disruption, source_node):
    geometry = (source_node.get("metadata") or {}).get("source_geometry")
    if _valid_source_geometry(geometry):
        return geometry, "GDACS source geometry"
    location = source_node.get("location")
    if location:
        return {"type": "Point", "coordinates": [location["longitude"], location["latitude"]]}, "ARES disruption coordinates"
    return None, ""


def _node_is_exposed(node, geometry, threshold_km):
    locations = node.get("locations") or ([node["location"]] if node.get("location") else [])
    if not locations:
        reason = "Entity coordinates are unavailable; geographic exposure cannot be assessed."
        if geometry is None:
            reason = "Entity coordinates and the disruption boundary/coordinates are unavailable; geographic exposure cannot be assessed."
        return None, reason
    if geometry is None:
        return None, "Disruption boundary and coordinates are unavailable; geographic exposure cannot be assessed."
    for location in locations:
        lat, lon = location["latitude"], location["longitude"]
        if geometry.get("type") == "Point":
            coords = geometry.get("coordinates") or []
            if len(coords) >= 2:
                try:
                    hazard_lon, hazard_lat = float(coords[0]), float(coords[1])
                    if -90 <= hazard_lat <= 90 and -180 <= hazard_lon <= 180:
                        distance = _haversine_km(lat, lon, hazard_lat, hazard_lon)
                        if distance <= threshold_km:
                            return True, f"Located {distance:.1f} km from the disruption point, within the configured {threshold_km:g} km threshold."
                except (TypeError, ValueError, OverflowError):
                    pass
        elif _inside_geometry(lat, lon, geometry):
            return True, "Entity coordinates fall inside the GDACS source-provided event boundary."
        elif _distance_to_geometry_km(lat, lon, geometry) <= threshold_km:
            return True, f"Entity coordinates fall within the configured {threshold_km:g} km buffer of the GDACS event boundary."
    if node.get("geographic_data_incomplete"):
        return None, "Some linked facility coordinates are unavailable; the known locations are outside the exposure area but all sites cannot be assessed."
    return False, "Available entity coordinates are outside the configured disruption exposure area."


def _propagation_adjacency(graph):
    nodes = {node["id"]: node for node in graph["nodes"]}
    forward, reverse = defaultdict(list), defaultdict(list)
    for edge in graph["edges"]:
        if edge["type"] == "affects":
            continue
        forward[edge["source"]].append((edge["target"], edge["type"]))
        reverse[edge["target"]].append((edge["source"], edge["type"]))
    return nodes, forward, reverse


def _walk_impacts(seeds, nodes, forward, reverse):
    paths = {}
    queue = deque((node_id, [node_id]) for node_id in seeds)
    seen = set(seeds)
    while queue:
        current, path = queue.popleft()
        current_type = nodes.get(current, {}).get("type")
        next_nodes = list(forward.get(current, []))
        # A facility failure exposes the materials stored there; a shipment failure
        # links back to the order it carries. Other relations remain directional.
        if current_type == "warehouse":
            next_nodes += [(source, relation) for source, relation in reverse.get(current, [])
                           if relation in {"stores", "origin", "destination"}]
        elif current_type == "shipment":
            next_nodes += [(source, relation) for source, relation in reverse.get(current, []) if relation == "transports"]
        for neighbor, relation in next_nodes:
            if neighbor in seen or nodes.get(neighbor, {}).get("type") == "disruption":
                continue
            seen.add(neighbor)
            paths[neighbor] = path + [relation, neighbor]
            queue.append((neighbor, path + [relation, neighbor]))
    return paths


def analyze_disruption_impact(disruption_id):
    disruption = get_object_or_404(Disruption, pk=disruption_id)
    graph = build_graph()
    nodes, forward, reverse = _propagation_adjacency(graph)
    source_id = f"disruption:{disruption.pk}"
    source_node = nodes.get(source_id)
    geometry, geometry_source = _source_geometry(disruption, source_node or {})
    threshold_km, threshold_type = _threshold(disruption)

    direct = set()
    direct_reasons = {}
    if disruption.affected_supplier_id:
        value = f"supplier:{disruption.affected_supplier_id}"
        direct.add(value)
        direct_reasons[value] = "ARES record explicitly links this supplier to the disruption."
    if disruption.affected_shipment_id:
        value = f"shipment:{disruption.affected_shipment_id}"
        direct.add(value)
        direct_reasons[value] = "ARES record explicitly links this shipment to the disruption."
    if source_id in nodes:
        direct.add(source_id)
        direct_reasons[source_id] = "This is the disruption being analyzed."

    geographic, geographic_reasons, insufficient = set(), {}, {}
    for node_id, node in nodes.items():
        if node["type"] == "disruption" and node_id == source_id:
            continue
        exposed, reason = _node_is_exposed(node, geometry, threshold_km)
        if exposed is True:
            geographic.add(node_id)
            geographic_reasons[node_id] = reason
        elif exposed is None:
            insufficient[node_id] = reason

    explicit_paths = _walk_impacts(direct - {source_id}, nodes, forward, reverse)
    geographic_paths = _walk_impacts(geographic, nodes, forward, reverse)
    impacted_paths = {**geographic_paths, **explicit_paths}

    results = []
    for node in graph["nodes"]:
        node_id = node["id"]
        if node_id in direct:
            classification, reason = "confirmed_affected", direct_reasons[node_id]
        elif node_id in geographic:
            classification, reason = "geographically_exposed", geographic_reasons[node_id]
        elif node_id in impacted_paths:
            classification = "potentially_impacted"
            path = impacted_paths[node_id]
            labels = [nodes.get(part, {}).get("name", part) if ":" in part else part for part in path]
            reason = "Connected by a supply-chain dependency path: " + " → ".join(labels) + "."
        elif node_id in insufficient:
            classification, reason = "insufficient_information", insufficient[node_id]
        else:
            classification, reason = "unaffected", "No geographic exposure or dependency path to this disruption was identified from available records."
        if classification in {"confirmed_affected", "geographically_exposed", "potentially_impacted"}:
            if node.get("geographic_data_unavailable"):
                reason += " Geographic exposure for this entity cannot be assessed because coordinates are unavailable."
            elif node.get("geographic_data_incomplete"):
                reason += " Some linked locations have no coordinates, so exposure at every site is not known."
            if geometry is None:
                reason += " The disruption boundary/coordinates are unavailable for a geographic check."
        results.append({"entity_id": node["entity_id"], "id": node_id, "type": node["type"],
                        "name": node["name"], "classification": classification, "reason": reason})

    counts = {classification: sum(1 for item in results if item["classification"] == classification)
              for classification in CLASSIFICATIONS}
    return {
        "disruption": {"id": str(disruption.pk), "title": disruption.title,
                       "severity": disruption.severity, "type": disruption.disruption_type},
        "method": {"geographic_source": geometry_source or "unavailable",
                   "threshold_km": threshold_km, "threshold_policy": threshold_type,
                   "region_name_matching_used": False,
                   "boundary_available": bool(geometry and geometry.get("type") in {"Polygon", "MultiPolygon"})},
        "counts": counts,
        "entities": results,
    }
