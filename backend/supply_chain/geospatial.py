"""Small, dependency-free GeoJSON validation helpers used at ARES data boundaries."""

import math
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError


MAX_EVENT_GEOMETRY_POSITIONS = 20_000
MAX_ROUTE_GEOMETRY_POSITIONS = 5_000


def _position(value, *, exact_dimensions=False):
    if not isinstance(value, (list, tuple)) or len(value) < 2 or len(value) > 3:
        raise ValueError("a coordinate position must contain longitude, latitude, and optional altitude")
    if exact_dimensions and len(value) not in {2, 3}:
        raise ValueError("a coordinate position must contain two or three dimensions")
    result = []
    for index, part in enumerate(value):
        if isinstance(part, bool) or not isinstance(part, (int, float, Decimal)):
            raise ValueError("GeoJSON coordinates must be numeric")
        number = float(part)
        if not math.isfinite(number):
            raise ValueError("GeoJSON coordinates must be finite")
        if index == 0 and not -180 <= number <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if index == 1 and not -90 <= number <= 90:
            raise ValueError("latitude must be between -90 and 90")
        result.append(number)
    return result


def normalize_geojson_geometry(geometry, *, allowed_types=None, max_positions=MAX_EVENT_GEOMETRY_POSITIONS):
    """Validate a GeoJSON geometry and return a compact, JSON-safe normalized copy."""
    allowed_types = set(allowed_types or {"Point", "Polygon", "MultiPolygon", "LineString", "MultiLineString"})
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a GeoJSON object")
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind not in allowed_types:
        raise ValueError("geometry type is unsupported")
    positions = 0

    def read_position(value):
        nonlocal positions
        positions += 1
        if positions > max_positions:
            raise ValueError(f"geometry exceeds the {max_positions} position limit")
        return _position(value)

    if kind == "Point":
        normalized = read_position(coordinates)
    elif kind == "LineString":
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            raise ValueError("a LineString needs at least two positions")
        normalized = [read_position(position) for position in coordinates]
    elif kind == "MultiLineString":
        if not isinstance(coordinates, (list, tuple)) or not coordinates:
            raise ValueError("a MultiLineString needs at least one line")
        normalized = []
        for line in coordinates:
            if not isinstance(line, (list, tuple)) or len(line) < 2:
                raise ValueError("each MultiLineString path needs at least two positions")
            normalized.append([read_position(position) for position in line])
    else:
        if kind == "Polygon":
            polygons = [coordinates]
        else:
            if not isinstance(coordinates, (list, tuple)) or not coordinates:
                raise ValueError("a MultiPolygon needs at least one polygon")
            polygons = list(coordinates)
        normalized_polygons = []
        for polygon in polygons:
            if not isinstance(polygon, (list, tuple)) or not polygon:
                raise ValueError("a polygon needs an exterior ring")
            rings = []
            for ring in polygon:
                if not isinstance(ring, (list, tuple)) or len(ring) < 4:
                    raise ValueError("each polygon ring needs at least four positions")
                points = [read_position(position) for position in ring]
                if points[0][:2] != points[-1][:2]:
                    raise ValueError("each polygon ring must be closed")
                if len({tuple(point[:2]) for point in points[:-1]}) < 3:
                    raise ValueError("each polygon ring must contain at least three distinct positions")
                rings.append(points)
            normalized_polygons.append(rings)
        normalized = normalized_polygons[0] if kind == "Polygon" else normalized_polygons
    return {"type": kind, "coordinates": normalized}


def validate_route_geometry(value):
    if value in (None, ""):
        return
    try:
        normalize_geojson_geometry(
            value,
            allowed_types={"LineString", "MultiLineString"},
            max_positions=MAX_ROUTE_GEOMETRY_POSITIONS,
        )
    except (TypeError, ValueError) as exc:
        raise DjangoValidationError(str(exc)) from exc
