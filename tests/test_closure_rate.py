import pytest

from lifemap_common import (
    annualized_closure_rate,
    geohash_bbox,
    geohash_encode,
    geohash_polygon,
    sumar_pares,
)


def test_tasa_de_cierre_anualizada():
    # 3 cierres en 730 días-negocio (2 años) = 1,5 cierres por año = 150 %
    assert annualized_closure_rate(3, 730) == pytest.approx(150.0)


def test_tasa_de_cierre_un_cierre_en_un_ano():
    assert annualized_closure_rate(1, 365) == pytest.approx(100.0)


def test_tasa_sin_cierres_es_cero():
    assert annualized_closure_rate(0, 1000) == 0.0


def test_tasa_sin_dias_negocio_no_esta_definida():
    assert annualized_closure_rate(5, 0) is None


def test_la_tasa_no_es_la_proporcion_de_cerrados():
    # 1 de 2 negocios cerrado (50 %) pero con 10 años-negocio la tasa anualizada es 5 %
    assert annualized_closure_rate(1, 2 * 5 * 365) == pytest.approx(10.0)


def test_sumar_pares():
    assert sumar_pares((1, 100), (0, 250)) == (1, 350)


def test_geohash_valor_conocido():
    # Ejemplo clásico de la especificación de geohash (Jutlandia, Dinamarca)
    assert geohash_encode(57.64911, 10.40744, 11) == "u4pruydqqvj"


def test_geohash_precision_6_de_medellin():
    assert geohash_encode(6.2442, -75.5812, 6) == "d34780"


def test_celda_contiene_la_coordenada():
    lat, lon = 6.2442, -75.5812
    celda = geohash_encode(lat, lon, 6)
    lat_min, lat_max, lon_min, lon_max = geohash_bbox(celda)
    assert lat_min <= lat <= lat_max
    assert lon_min <= lon <= lon_max


def test_poligono_geojson_cerrado():
    anillo = geohash_polygon("d34780")["coordinates"][0]
    assert anillo[0] == anillo[-1]
    assert len(anillo) == 5
