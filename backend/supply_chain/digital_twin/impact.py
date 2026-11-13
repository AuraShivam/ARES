import math
from collections import defaultdict, deque

from django.conf import settings
from django.shortcuts import get_object_or_404

from supply_chain.geospatial import normalize_geojson_geometry
from supply_chain.models import Disruption
from .graph import build_graph


CLASSIFICATIONS = (
    "confirmed_operational_disruption",
    "confirmed_geographical_intersection",
    "potential_geographical_exposure",
    "indirect_supply_chain_dependency",
    "unaffected",
    "unknown_insufficient_data",
)
LEGACY_CLASSIFICATIONS = (
    "confirmed_affected", "geographically_exposed", "potentially_impacted",
    "unaffected", "insufficient_information",
)
LEGACY_MAP = {
    "confirmed_operational_disruption": "confirmed_affected",
    "confirmed_geographical_intersection": "geographically_exposed",
    "potential_geographical_exposure": "geographically_exposed",
    "indirect_supply_chain_dependency": "potentially_impacted",
    "unaffected": "unaffected",
    "unknown_insufficient_data": "insufficient_information",
}
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
    try:
        normalize_geojson_geometry(
            geometry, allowed_types={"Point", "Polygon", "MultiPolygon"}, max_positions=20_000,
        )
    except (TypeError, ValueError):
        return False
    return True


def _point_in_ring(lat, lon, ring):
    inside = False
    points = []
    for pair in ring:
        point_lat, point_lon = float(pair[1]), float(pair[0])
        while point_lon - lon > 180:
            point_lon -= 360
        while point_lon - lon < -180:
            point_lon += 360
        points.append((point_lat, point_lon))
    previous = points[-1]
    for current in points:
        y1, x1 = previous
        y2, x2 = current
        crosses = ((y1 > lat) != (y2 > lat)) and (lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-15) + x1)
        if crosses:
            inside = not inside
        previous = current
    return inside


def _point_on_ring(lat, lon, ring):
    return any(_distance_point_to_segment_km(lat, lon, start, end) <= 0.001
               for start, end in zip(ring, ring[1:]))


def _inside_geometry(lat, lon, geometry):
    if geometry.get("type") == "Polygon":
        rings = geometry.get("coordinates") or []
        if not rings or not (_point_in_ring(lat, lon, rings[0]) or _point_on_ring(lat, lon, rings[0])):
            return False
        return not any(_point_in_ring(lat, lon, ring) and not _point_on_ring(lat, lon, ring) for ring in rings[1:])
    if geometry.get("type") == "MultiPolygon":
        for polygon in geometry.get("coordinates") or []:
            if polygon and (_point_in_ring(lat, lon, polygon[0]) or _point_on_ring(lat, lon, polygon[0])) and not any(
                _point_in_ring(lat, lon, ring) and not _point_on_ring(lat, lon, ring) for ring in polygon[1:]
            ):
                return True
    return False


def _local_xy(lat, lon, origin_lat, origin_lon):
    scale_x = math.cos(math.radians(origin_lat))
    delta_lon = (lon - origin_lon + 180) % 360 - 180
    return (delta_lon * scale_x * 111.195, (lat - origin_lat) * 111.195)


def _point_segment_distance(point, start, end):
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    ratio = 0 if dx == 0 and dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy))


def _distance_to_ring_km(lat, lon, ring):
    return min((_distance_point_to_segment_km(lat, lon, ring[index], ring[index + 1])
                for index in range(len(ring) - 1)), default=float("inf"))


def _initial_bearing_radians(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lon = math.radians((lon2 - lon1 + 180) % 360 - 180)
    return math.atan2(math.sin(delta_lon) * math.cos(phi2),
                      math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lon))


def _distance_point_to_segment_km(lat, lon, start, end):
    start_lon, start_lat = float(start[0]), float(start[1])
    end_lon, end_lat = float(end[0]), float(end[1])
    segment_angle = _haversine_km(start_lat, start_lon, end_lat, end_lon) / EARTH_RADIUS_KM
    point_angle = _haversine_km(start_lat, start_lon, lat, lon) / EARTH_RADIUS_KM
    if segment_angle <= 1e-12 or point_angle <= 1e-12:
        return _haversine_km(lat, lon, start_lat, start_lon)
    bearing_to_point = _initial_bearing_radians(start_lat, start_lon, lat, lon)
    bearing_to_end = _initial_bearing_radians(start_lat, start_lon, end_lat, end_lon)
    difference = bearing_to_point - bearing_to_end
    cross_track = math.asin(max(-1.0, min(1.0, math.sin(point_angle) * math.sin(difference))))
    along_track = math.atan2(math.sin(point_angle) * math.cos(difference), math.cos(point_angle))
    if 0 <= along_track <= segment_angle:
        return abs(cross_track) * EARTH_RADIUS_KM
    return min(_haversine_km(lat, lon, start_lat, start_lon), _haversine_km(lat, lon, end_lat, end_lon))


def _distance_to_geometry_km(lat, lon, geometry):
    return min((_distance_to_ring_km(lat, lon, ring) for ring in _rings(geometry)), default=float("inf"))


def _route_lines(geometry):
    if geometry.get("type") == "LineString":
        return [geometry.get("coordinates") or []]
    return geometry.get("coordinates") or []


def _orientation(a, b, c):
    return (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])


def _segments_intersect(a, b, c, d):
    def on_segment(p, q, r):
        return (min(p[0], r[0]) - 1e-9 <= q[0] <= max(p[0], r[0]) + 1e-9
                and min(p[1], r[1]) - 1e-9 <= q[1] <= max(p[1], r[1]) + 1e-9)

    o1, o2, o3, o4 = _orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b)
    if ((o1 > 0 > o2 or o2 > 0 > o1) and (o3 > 0 > o4 or o4 > 0 > o3)):
        return True
    return ((abs(o1) <= 1e-9 and on_segment(a, c, b)) or (abs(o2) <= 1e-9 and on_segment(a, d, b))
            or (abs(o3) <= 1e-9 and on_segment(c, a, d)) or (abs(o4) <= 1e-9 and on_segment(c, b, d)))


def _route_intersects_polygon(route_geometry, polygon_geometry):
    rings = _rings(polygon_geometry)
    for line in _route_lines(route_geometry):
        for longitude, latitude, *_ in line:
            if _inside_geometry(latitude, longitude, polygon_geometry):
                return True
        for start, end in zip(line, line[1:]):
            origin = (float(start[1]), float(start[0]))
            route_start = _local_xy(start[1], start[0], *origin)
            route_end = _local_xy(end[1], end[0], *origin)
            for ring in rings:
                projected = [_local_xy(position[1], position[0], *origin) for position in ring]
                if any(_segments_intersect(route_start, route_end, boundary_start, boundary_end)
                       for boundary_start, boundary_end in zip(projected, projected[1:])):
                    return True
    return False


def _distance_route_to_point_km(route_geometry, lat, lon):
    best = float("inf")
    for line in _route_lines(route_geometry):
        for start, end in zip(line, line[1:]):
            best = min(best, _distance_point_to_segment_km(lat, lon, start, end))
    return best


def _distance_route_to_geometry_km(route_geometry, polygon_geometry):
    best = float("inf")
    for line in _route_lines(route_geometry):
        for longitude, latitude, *_ in line:
            best = min(best, _distance_to_geometry_km(latitude, longitude, polygon_geometry))
        for start, end in zip(line, line[1:]):
            origin_lat, origin_lon = float(start[1]), float(start[0])
            route_start = _local_xy(start[1], start[0], origin_lat, origin_lon)
            route_end = _local_xy(end[1], end[0], origin_lat, origin_lon)
            for ring in _rings(polygon_geometry):
                boundary = [_local_xy(position[1], position[0], origin_lat, origin_lon) for position in ring]
                for index, boundary_start in enumerate(boundary[:-1]):
                    boundary_end = boundary[index + 1]
                    if _segments_intersect(route_start, route_end, boundary_start, boundary_end):
                        return 0.0
                    best = min(best,
                               _point_segment_distance(route_start, boundary_start, boundary_end),
                               _point_segment_distance(route_end, boundary_start, boundary_end),
                               _point_segment_distance(boundary_start, route_start, route_end),
                               _point_segment_distance(boundary_end, route_start, route_end))
    return best


def _threshold(disruption):
    configured = getattr(settings, "ARES_DIGITAL_TWIN_EXPOSURE_THRESHOLDS_KM", {})
    kind = (disruption.disruption_type or "").strip().casefold()
    type_values = configured.get(kind, {}) if isinstance(configured.get(kind), dict) else {}
    fallback = configured.get("default", {}) if isinstance(configured.get("default"), dict) else {}
    value = type_values.get(disruption.severity, fallback.get(disruption.severity, 0))
    return float(value), kind or "default"


def _source_geometry(disruption, source_node):
    geometry = (source_node.get("metadata") or {}).get("source_geometry")
    if _valid_source_geometry(geometry):
        return normalize_geojson_geometry(geometry, allowed_types={"Point", "Polygon", "MultiPolygon"}), "GDACS source geometry"
    location = source_node.get("location")
    if location:
        return {"type": "Point", "coordinates": [location["longitude"], location["latitude"]]}, "ARES disruption coordinates"
    return None, ""


def _node_is_exposed(node, geometry, threshold_km):
    metadata = node.get("metadata") or {}
    locations = node.get("locations") or ([node["location"]] if node.get("location") else [])
    route_geometry = metadata.get("route_geometry")
    if route_geometry:
        try:
            route_geometry = normalize_geojson_geometry(
                route_geometry, allowed_types={"LineString", "MultiLineString"}, max_positions=5_000,
            )
        except (TypeError, ValueError):
            route_geometry = None
    if not locations and not route_geometry:
        return None, {"reason": "Entity coordinates and a supplied route path are unavailable; geographic exposure cannot be assessed.", "basis": "missing_entity_geometry"}
    if geometry is None:
        return None, {"reason": "Disruption boundary and coordinates are unavailable; geographic exposure cannot be assessed.", "basis": "missing_event_geometry"}

    observations = []
    if route_geometry:
        if geometry.get("type") in {"Polygon", "MultiPolygon"} and _route_intersects_polygon(route_geometry, geometry):
            source = metadata.get("route_geometry_source") or "unspecified route geometry source"
            return "confirmed_geographical_intersection", {
                "reason": "The supplied shipment path intersects the GDACS source event polygon.",
                "basis": "supplied_route_intersects_source_polygon",
                "route_geometry_source": source,
            }
        if geometry.get("type") == "Point":
            coordinates = geometry.get("coordinates") or []
            distance = _distance_route_to_point_km(route_geometry, float(coordinates[1]), float(coordinates[0]))
            if distance <= threshold_km:
                return "potential_geographical_exposure", {
                    "reason": f"The supplied shipment path passes within the configured {threshold_km:g} km policy buffer of a GDACS point event.",
                    "basis": "route_within_point_event_policy_buffer",
                    "distance_km": round(distance, 2),
                    "threshold_km": threshold_km,
                    "route_geometry_source": metadata.get("route_geometry_source") or "unspecified route geometry source",
                }
        else:
            distance = _distance_route_to_geometry_km(route_geometry, geometry)
            if distance <= threshold_km:
                return "potential_geographical_exposure", {
                    "reason": f"The supplied shipment path is within the configured {threshold_km:g} km policy buffer of the GDACS event boundary.",
                    "basis": "route_within_polygon_policy_buffer",
                    "distance_km": round(distance, 2),
                    "threshold_km": threshold_km,
                    "route_geometry_source": metadata.get("route_geometry_source") or "unspecified route geometry source",
                }

    for location in locations:
        lat, lon = location["latitude"], location["longitude"]
        if geometry.get("type") == "Point":
            coordinates = geometry.get("coordinates") or []
            distance = _haversine_km(lat, lon, float(coordinates[1]), float(coordinates[0]))
            if distance <= threshold_km:
                observations.append(("potential_geographical_exposure", {
                    "reason": f"Recorded location is {distance:.1f} km from the GDACS event point, within the configured {threshold_km:g} km policy buffer.",
                    "basis": "point_event_policy_buffer", "distance_km": round(distance, 2),
                    "threshold_km": threshold_km, "location_source": location.get("source"),
                }))
        elif _inside_geometry(lat, lon, geometry):
            observations.append(("confirmed_geographical_intersection", {
                "reason": "Recorded entity coordinates fall inside the GDACS source-provided event polygon.",
                "basis": "coordinate_inside_source_polygon", "location_source": location.get("source"),
            }))
        else:
            distance = _distance_to_geometry_km(lat, lon, geometry)
            if distance <= threshold_km:
                observations.append(("potential_geographical_exposure", {
                    "reason": f"Recorded location is within the configured {threshold_km:g} km policy buffer of the GDACS event boundary.",
                    "basis": "polygon_policy_buffer", "distance_km": round(distance, 2),
                    "threshold_km": threshold_km, "location_source": location.get("source"),
                }))
    priorities = {"confirmed_geographical_intersection": 0, "potential_geographical_exposure": 1}
    if observations:
        return min(observations, key=lambda value: priorities[value[0]])
    if node.get("geographic_data_incomplete"):
        return None, {"reason": "Known locations are outside the exposure area, but one or more linked facility coordinates are missing.", "basis": "incomplete_entity_coordinates"}
    return False, {"reason": "Available entity coordinates and any supplied route path are outside the configured exposure area.", "basis": "checked_outside_exposure_area"}


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
    source_metadata = (source_node or {}).get("metadata") or {}
    source_context = {
        "source_name": source_metadata.get("source_name") or disruption.source_name or "ARES record",
        "source_event_id": source_metadata.get("source_event_id"),
        "source_event_external_id": source_metadata.get("source_event_external_id"),
        "source_event_episode_id": source_metadata.get("source_event_episode_id"),
        "source_event_type": source_metadata.get("source_event_type"),
        "source_event_title": source_metadata.get("source_event_title"),
        "source_alert_level": source_metadata.get("source_alert_level"),
        "source_event_lifecycle": source_metadata.get("source_event_lifecycle"),
        "source_event_issued_at": source_metadata.get("source_event_issued_at"),
        "source_event_effective_at": source_metadata.get("source_event_effective_at"),
        "source_event_expires_at": source_metadata.get("source_event_expires_at"),
        "source_event_url": source_metadata.get("source_event_url"),
        "source_event_metrics": source_metadata.get("source_event_metrics", {}),
        "source_geometry_type": geometry.get("type") if geometry else None,
        "source_geometry_status": source_metadata.get("source_geometry_status"),
    }

    operational = set()
    operational_evidence = {}
    for entity_type, entity_id in (("supplier", disruption.affected_supplier_id), ("shipment", disruption.affected_shipment_id)):
        if entity_id:
            node_id = f"{entity_type}:{entity_id}"
            operational.add(node_id)
            operational_evidence[node_id] = {
                "reason": f"ARES disruption record explicitly links this {entity_type}; GDACS itself does not confirm operational impact.",
                "basis": "explicit_operator_entered_ares_link",
            }

    geographic, geographic_evidence, insufficient = set(), {}, {}
    for node_id, node in nodes.items():
        if node["type"] == "disruption":
            continue
        exposed, evidence = _node_is_exposed(node, geometry, threshold_km)
        if exposed in {"confirmed_geographical_intersection", "potential_geographical_exposure"}:
            geographic.add(node_id)
            geographic_evidence[node_id] = (exposed, evidence)
        elif exposed is None:
            insufficient[node_id] = evidence

    explicit_paths = _walk_impacts(operational, nodes, forward, reverse)
    geographic_paths = _walk_impacts(geographic, nodes, forward, reverse)
    impacted_paths = {**geographic_paths, **explicit_paths}

    results = []
    for node in graph["nodes"]:
        node_id = node["id"]
        if node_id == source_id:
            classification = "unknown_insufficient_data"
            evidence = {"reason": "This source event is the scenario being analyzed, not an affected supply-chain entity.", "basis": "scenario_source_event"}
        elif node_id in operational:
            classification, evidence = "confirmed_operational_disruption", operational_evidence[node_id]
        elif node_id in geographic:
            classification, evidence = geographic_evidence[node_id]
        elif node_id in impacted_paths:
            classification = "indirect_supply_chain_dependency"
            path = impacted_paths[node_id]
            labels = [nodes.get(part, {}).get("name", part) if ":" in part else part for part in path]
            root = path[0]
            evidence = {
                "reason": "Connected to an exposed or explicitly linked entity through stored supply-chain relationships: " + " → ".join(labels) + ".",
                "basis": "recorded_dependency_path", "path": path, "path_labels": labels,
                "root_entity_id": root,
            }
        elif node_id in insufficient:
            classification, evidence = "unknown_insufficient_data", insufficient[node_id]
        else:
            classification = "unaffected"
            evidence = {"reason": "No geographic exposure or dependency path was identified from the available records.", "basis": "no_exposure_or_dependency_found"}
        evidence.update(source_context)
        if classification in {"confirmed_operational_disruption", "confirmed_geographical_intersection",
                              "potential_geographical_exposure", "indirect_supply_chain_dependency"}:
            if node.get("geographic_data_unavailable"):
                evidence["geographic_caveat"] = "Entity coordinates are unavailable, so separate geographic exposure cannot be assessed."
            elif node.get("geographic_data_incomplete"):
                evidence["geographic_caveat"] = "Some linked locations have no coordinates, so exposure at every site is not known."
        legacy_classification = LEGACY_MAP[classification]
        results.append({
            "entity_id": node["entity_id"], "id": node_id, "type": node["type"], "name": node["name"],
            "classification": legacy_classification,
            "exposure_classification": classification,
            "reason": evidence["reason"],
            "evidence": evidence,
        })

    exposure_counts = {classification: sum(1 for item in results if item["exposure_classification"] == classification)
                       for classification in CLASSIFICATIONS}
    legacy_counts = {classification: sum(1 for item in results if item["classification"] == classification)
                     for classification in LEGACY_CLASSIFICATIONS}
    return {
        "disruption": {"id": str(disruption.pk), "title": disruption.title,
                       "severity": disruption.severity, "type": disruption.disruption_type},
        "method": {"geographic_source": geometry_source or "unavailable",
                   "threshold_km": threshold_km, "threshold_policy": threshold_type,
                   "region_name_matching_used": False,
                   "boundary_available": bool(geometry and geometry.get("type") in {"Polygon", "MultiPolygon"})},
        "counts": legacy_counts,
        "exposure_counts": exposure_counts,
        "entities": results,
    }
