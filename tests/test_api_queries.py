import pytest

from queries import (
    BadRequest,
    category_filter,
    clean_json,
    closure_stats_query,
    haversine_m,
    mark_min_days,
    near_query,
    parse_bool,
    parse_point,
    parse_polygon,
    summarize_zone,
    within_query,
)

SQUARE = {"type": "Polygon", "coordinates": [[[-75.6, 6.2], [-75.5, 6.2], [-75.5, 6.3], [-75.6, 6.3], [-75.6, 6.2]]]}


# --- parámetros ---

def test_punto_obligatorio():
    with pytest.raises(BadRequest):
        parse_point({"lon": "-75.5"})


def test_punto_fuera_de_rango():
    with pytest.raises(BadRequest):
        parse_point({"lat": "91", "lon": "0"})


def test_punto_no_numerico():
    with pytest.raises(BadRequest):
        parse_point({"lat": "abc", "lon": "0"})


def test_punto_devuelve_lon_lat():
    assert parse_point({"lat": "6.24", "lon": "-75.58"}) == (-75.58, 6.24)


def test_bool():
    assert parse_bool({"x": "true"}, "x") is True
    assert parse_bool({}, "x") is False
    with pytest.raises(BadRequest):
        parse_bool({"x": "quizas"}, "x")


# --- categoría ---

def _matches(category, categories):
    import re

    f = category_filter(category)["categories"]
    return re.search(f["$regex"], categories, re.IGNORECASE) is not None


def test_categoria_coincide_con_un_elemento_completo():
    assert _matches("Pizza", "Restaurants, Pizza, Italian")
    assert _matches("pizza", "Pizza")
    assert not _matches("Pizza", "Pizza Delivery, Restaurants")


def test_categoria_con_caracteres_especiales():
    assert _matches("Bars (Sports)", "Nightlife, Bars (Sports)")


def test_sin_categoria_no_filtra():
    assert category_filter(None) == {}


# --- consultas geoespaciales ---

def test_near_usa_near_con_lon_lat_y_radio():
    q = near_query(-75.58, 6.24, 500, "Pizza")
    assert q["location"]["$near"]["$geometry"]["coordinates"] == [-75.58, 6.24]
    assert q["location"]["$near"]["$maxDistance"] == 500
    assert "categories" in q


def test_within_usa_geowithin():
    assert within_query(SQUARE)["location"]["$geoWithin"]["$geometry"] == SQUARE


def test_poligono_valido_y_feature():
    assert parse_polygon(SQUARE) == SQUARE
    assert parse_polygon({"type": "Feature", "geometry": SQUARE, "properties": {}}) == SQUARE


@pytest.mark.parametrize("body", [
    {"type": "Point", "coordinates": [0, 0]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},  # sin cerrar
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},  # menos de 4 posiciones
    {"type": "Polygon", "coordinates": [[[0, 0], [200, 0], [1, 1], [0, 0]]]},  # fuera de rango
    {"type": "Polygon", "coordinates": [[["a", 0], [1, 0], [1, 1], ["a", 0]]]},
    [],
])
def test_poligonos_invalidos(body):
    with pytest.raises(BadRequest):
        parse_polygon(body)


def test_haversine_un_grado_de_latitud():
    assert haversine_m(0, 0, 0, 1) == pytest.approx(111_195, rel=1e-3)


# --- /zones/summary ---

def test_resumen_de_zona():
    grupo = {"n_businesses": 2, "closures": 1, "business_days": 730, "n_reviews": 4, "stars": 14,
             "negative": 1, "neutral": 0, "positive": 3}
    r = summarize_zone([grupo], -75.58, 6.24, 1000, 365)
    assert r["closure"]["closure_rate"] == pytest.approx(50.0)  # 1 cierre en 2 años-negocio
    assert r["closure"]["meets_min_days"] is True
    assert r["sentiment"]["mean_stars"] == pytest.approx(3.5)
    assert r["sentiment"]["sentiment_score"] == pytest.approx(0.5)  # (3 - 1) / 4
    assert r["sentiment"]["pct_positive"] == pytest.approx(75.0)


def test_resumen_de_zona_vacia():
    r = summarize_zone([], 0, 0, 1000, 3650)
    assert r["n_businesses"] == 0
    assert r["closure"]["closure_rate"] is None
    assert r["sentiment"]["sentiment_score"] is None


# --- /stats/closure ---

def test_estadisticas_por_categoria_filtran_por_minimo_del_grupo():
    coleccion, query, projection, sort = closure_stats_query("category", 3650, False, "desc")
    assert coleccion == "closure_by_category"
    assert query == {"business_days": {"$gte": 3650}}
    assert sort[0] == ("closure_rate", -1)
    assert "category" in projection


def test_estadisticas_por_celda_incluyen_geometria():
    coleccion, query, projection, _ = closure_stats_query("cell", 3650, True, "asc")
    assert coleccion == "closure_by_geohash"
    assert query == {}
    assert projection["geometry"] == 1 and projection["geohash"] == 1


def test_estadisticas_agrupacion_invalida():
    with pytest.raises(BadRequest):
        closure_stats_query("city", 3650, False, "desc")


def test_marca_minimo_pedido():
    rows = mark_min_days([{"business_days": 400}, {"business_days": 100}], 365)
    assert [r["meets_min_days"] for r in rows] == [True, False]


def test_nan_a_null():
    assert clean_json({"a": float("nan"), "b": [1.0, float("inf")]}) == {"a": None, "b": [1.0, None]}
