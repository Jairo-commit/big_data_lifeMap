"""Validación de parámetros y construcción de consultas de MongoDB para la API de LifeMap.

Solo usa la biblioteca estándar: se prueba con pytest sin MongoDB, Flask ni Spark
(tests/test_api_queries.py). Compatible con Python 3.8 (el de la imagen de Spark).
"""

import math
import re

EARTH_RADIUS_M = 6_371_008.8

# Mínimo de días-negocio por defecto, el mismo de los jobs de Spark (MIN_BUSINESS_DAYS)
DEFAULT_MIN_BUSINESS_DAYS = 3650

# Campos de un negocio que devuelve la API
BUSINESS_PROJECTION = {
    "_id": 0,
    "business_id": 1,
    "name": 1,
    "address": 1,
    "city": 1,
    "state": 1,
    "stars": 1,
    "review_count": 1,
    "is_open": 1,
    "categories": 1,
    "location": 1,
    "days_business": 1,
    "event": 1,
}

# Tasas por categoría o por celda: colecciones que escribe spark_batch/closure_rates.py
CLOSURE_SOURCES = {
    "category": {
        "collection": "closure_by_category",
        "key": "category",
        "extra_fields": [],
    },
    "cell": {
        "collection": "closure_by_geohash",
        "key": "geohash",
        "extra_fields": ["n_reviews", "n_negative", "pct_negative", "geohash_precision", "centroid", "geometry"],
    },
}


class BadRequest(ValueError):
    """Parámetro inválido: la API responde 400 con este mensaje."""


# ---------------------------------------------------------------------------
# Parámetros
# ---------------------------------------------------------------------------

def parse_float(args, name, default=None, minimum=None, maximum=None):
    raw = args.get(name)
    if raw is None or raw == "":
        if default is None:
            raise BadRequest(f"falta el parámetro '{name}'")
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"'{name}' debe ser un número") from None
    if math.isnan(value) or math.isinf(value):
        raise BadRequest(f"'{name}' debe ser un número finito")
    if minimum is not None and value < minimum:
        raise BadRequest(f"'{name}' debe ser >= {minimum}")
    if maximum is not None and value > maximum:
        raise BadRequest(f"'{name}' debe ser <= {maximum}")
    return value


def parse_int(args, name, default, minimum=None, maximum=None):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"'{name}' debe ser un entero") from None
    if minimum is not None and value < minimum:
        raise BadRequest(f"'{name}' debe ser >= {minimum}")
    if maximum is not None and value > maximum:
        raise BadRequest(f"'{name}' debe ser <= {maximum}")
    return value


def parse_bool(args, name, default=False):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    value = str(raw).strip().lower()
    if value in ("1", "true", "yes", "si", "sí"):
        return True
    if value in ("0", "false", "no"):
        return False
    raise BadRequest(f"'{name}' debe ser true o false")


def parse_point(args):
    """(lon, lat) de los parámetros lat y lon, obligatorios."""
    lat = parse_float(args, "lat", minimum=-90, maximum=90)
    lon = parse_float(args, "lon", minimum=-180, maximum=180)
    return lon, lat


def parse_category(args):
    category = (args.get("category") or "").strip()
    return category or None


# ---------------------------------------------------------------------------
# Filtros y geometría
# ---------------------------------------------------------------------------

def category_filter(category):
    """Filtro por una categoría completa dentro de `categories`.

    En los datos de Yelp `categories` es una cadena separada por comas
    ("Pizza, Restaurants, Italian"): la categoría debe ser uno de esos elementos completos,
    sin distinguir mayúsculas, así que "Pizza" no coincide con "Pizza Delivery".
    """
    if not category:
        return {}
    pattern = r"(^|,)\s*" + re.escape(category) + r"\s*(,|$)"
    return {"categories": {"$regex": pattern, "$options": "i"}}


def geojson_point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def haversine_m(lon1, lat1, lon2, lat2):
    """Distancia en metros entre dos puntos (lon, lat) sobre la esfera."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _validate_ring(ring, where):
    if not isinstance(ring, list) or len(ring) < 4:
        raise BadRequest(f"{where}: un anillo necesita al menos 4 posiciones")
    for position in ring:
        if (not isinstance(position, list) or len(position) < 2
                or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in position[:2])):
            raise BadRequest(f"{where}: cada posición debe ser [lon, lat]")
        lon, lat = position[0], position[1]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise BadRequest(f"{where}: posición fuera de rango {position}")
    if ring[0][:2] != ring[-1][:2]:
        raise BadRequest(f"{where}: el anillo debe estar cerrado (primera posición = última)")


def parse_polygon(body):
    """Geometría GeoJSON Polygon o MultiPolygon, sola o dentro de un Feature."""
    if not isinstance(body, dict):
        raise BadRequest("el cuerpo debe ser un objeto GeoJSON (Polygon, MultiPolygon o Feature)")
    geometry = body.get("geometry") if body.get("type") == "Feature" else body
    if not isinstance(geometry, dict):
        raise BadRequest("el Feature no tiene 'geometry'")
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coordinates]
    elif kind == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise BadRequest("MultiPolygon sin polígonos")
        polygons = coordinates
    else:
        raise BadRequest("la geometría debe ser de tipo Polygon o MultiPolygon")
    for i, polygon in enumerate(polygons):
        if not isinstance(polygon, list) or not polygon:
            raise BadRequest(f"polígono {i}: sin anillos")
        for j, ring in enumerate(polygon):
            _validate_ring(ring, f"polígono {i}, anillo {j}")
    return {"type": kind, "coordinates": coordinates}


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def near_query(lon, lat, radius_m, category=None):
    """Negocios a menos de radius_m metros del punto, del más cercano al más lejano ($near)."""
    query = {
        "location": {
            "$near": {
                "$geometry": geojson_point(lon, lat),
                "$maxDistance": radius_m,
            }
        }
    }
    query.update(category_filter(category))
    return query


def within_query(geometry, category=None):
    """Negocios dentro de la geometría ($geoWithin)."""
    query = {"location": {"$geoWithin": {"$geometry": geometry}}}
    query.update(category_filter(category))
    return query


def zone_summary_pipeline(lon, lat, radius_m, min_days, category=None):
    """Resumen de los negocios a menos de radius_m metros del punto ($geoNear).

    - Tasa de cierre anualizada: cierres / (días-negocio / 365) * 100, como en Spark.
    - Sentimiento de las reseñas con la misma regla de las etiquetas del modelo
      (1-2 estrellas negativo, 3 neutral, 4-5 positivo). `sentiment_score` es la media con
      negativo = -1, neutral = 0 y positivo = 1: va de -1 a 1.
    """
    geo_near = {
        "near": geojson_point(lon, lat),
        "distanceField": "distance_m",
        "maxDistance": radius_m,
        "spherical": True,
        "key": "location",
    }
    if category:
        geo_near["query"] = category_filter(category)

    return [
        {"$geoNear": geo_near},
        {"$project": {"_id": 0, "business_id": 1, "event": 1, "days_business": 1, "distance_m": 1}},
        {"$lookup": {
            "from": "reviews",
            "localField": "business_id",
            "foreignField": "business_id",
            "pipeline": [
                {"$group": {
                    "_id": None,
                    "n": {"$sum": 1},
                    "stars": {"$sum": "$stars"},
                    "negative": {"$sum": {"$cond": [{"$lte": ["$stars", 2]}, 1, 0]}},
                    "neutral": {"$sum": {"$cond": [{"$eq": ["$stars", 3]}, 1, 0]}},
                    "positive": {"$sum": {"$cond": [{"$gte": ["$stars", 4]}, 1, 0]}},
                }},
            ],
            "as": "reviews",
        }},
        {"$unwind": {"path": "$reviews", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": None,
            "n_businesses": {"$sum": 1},
            "closures": {"$sum": {"$ifNull": ["$event", 0]}},
            "business_days": {"$sum": {"$ifNull": ["$days_business", 0]}},
            "n_reviews": {"$sum": {"$ifNull": ["$reviews.n", 0]}},
            "stars": {"$sum": {"$ifNull": ["$reviews.stars", 0]}},
            "negative": {"$sum": {"$ifNull": ["$reviews.negative", 0]}},
            "neutral": {"$sum": {"$ifNull": ["$reviews.neutral", 0]}},
            "positive": {"$sum": {"$ifNull": ["$reviews.positive", 0]}},
            "max_distance_m": {"$max": "$distance_m"},
        }},
    ]


def summarize_zone(groups, lon, lat, radius_m, min_days, category=None):
    """Respuesta de /zones/summary a partir del resultado de zone_summary_pipeline."""
    g = groups[0] if groups else {}
    n_businesses = g.get("n_businesses", 0)
    closures = g.get("closures", 0)
    business_days = g.get("business_days", 0)
    n_reviews = g.get("n_reviews", 0)
    negative, neutral, positive = g.get("negative", 0), g.get("neutral", 0), g.get("positive", 0)

    def pct(n):
        return n / n_reviews * 100 if n_reviews else None

    return {
        "center": geojson_point(lon, lat),
        "radius_m": radius_m,
        "category": category,
        "n_businesses": n_businesses,
        "closure": {
            "closures": closures,
            "business_days": business_days,
            "closure_rate": closures / (business_days / 365) * 100 if business_days else None,
            "min_business_days": min_days,
            "meets_min_days": business_days >= min_days,
        },
        "sentiment": {
            "n_reviews": n_reviews,
            "mean_stars": g.get("stars", 0) / n_reviews if n_reviews else None,
            "sentiment_score": (positive - negative) / n_reviews if n_reviews else None,
            "pct_negative": pct(negative),
            "pct_neutral": pct(neutral),
            "pct_positive": pct(positive),
        },
    }


def closure_stats_query(by, min_days, include_below_min, order):
    """Colección, filtro, orden y proyección para /stats/closure.

    El mínimo de días-negocio se aplica al grupo (categoría o celda), no a cada negocio:
    un grupo con menos exposición tiene una tasa ruidosa. Con include_below_min los grupos bajo
    el mínimo también se devuelven, marcados con meets_min_days = false.
    """
    if by not in CLOSURE_SOURCES:
        raise BadRequest("'by' debe ser 'category' o 'cell'")
    if order not in ("desc", "asc"):
        raise BadRequest("'order' debe ser 'desc' o 'asc'")
    source = CLOSURE_SOURCES[by]
    query = {} if include_below_min else {"business_days": {"$gte": min_days}}
    projection = {"_id": 0, source["key"]: 1, "n_businesses": 1, "closures": 1, "business_days": 1,
                  "closure_rate": 1}
    for field in source["extra_fields"]:
        projection[field] = 1
    direction = -1 if order == "desc" else 1
    sort = [("closure_rate", direction), ("business_days", -1)]
    return source["collection"], query, projection, sort


def mark_min_days(rows, min_days):
    """meets_min_days según el mínimo pedido (el guardado por Spark usa el mínimo del job)."""
    for row in rows:
        row["meets_min_days"] = (row.get("business_days") or 0) >= min_days
    return rows


# ---------------------------------------------------------------------------
# Respuestas
# ---------------------------------------------------------------------------

def clean_json(value):
    """NaN e infinitos (campos vacíos de la ingesta con pandas) a None: JSON válido."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_json(v) for v in value]
    return value


def with_distance(business, lon, lat):
    """Agrega distance_m (desde el punto de la consulta) a un negocio con location GeoJSON."""
    coordinates = (business.get("location") or {}).get("coordinates")
    if coordinates and len(coordinates) >= 2:
        business["distance_m"] = round(haversine_m(lon, lat, coordinates[0], coordinates[1]), 1)
    return business
