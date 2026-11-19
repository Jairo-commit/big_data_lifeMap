"""Ventanas geoespaciales y hotspots (spark_batch/geo_windows.py), sin Spark ni MongoDB."""

from datetime import datetime, timedelta

import pytest

from geo_windows import (
    EPOCH,
    build_window_docs,
    calibrate_threshold,
    from_epoch_seconds,
    hotspot_decision,
    missing_previous_ids,
    parse_day,
    percent,
    previous_window_start,
    quantile,
    standard_error_pp,
    summarize_deltas,
    window_id,
    window_offset_days,
)

T = datetime(2021, 1, 1)
DAY = 86400


def seconds(dt):
    return int((dt - EPOCH).total_seconds())


def row(geohash="dr4e3x", start=T, n=40, negative=20, stars_negative=18, days=30):
    return {
        "geohash": geohash,
        "window_start": seconds(start),
        "window_end": seconds(start + timedelta(days=days)),
        "n_reviews": n,
        "n_negative": negative,
        "n_neutral": 5,
        "n_positive": n - negative - 5,
        "n_negative_stars": stars_negative,
    }


# --- alineación de ventanas con T -------------------------------------------------------------


def test_las_ventanas_de_30_dias_se_alinean_con_la_fecha_de_corte():
    # 2021-01-01 son 18628 días desde 1970 = 620 * 30 + 28: Spark debe desplazar 28 días
    assert window_offset_days("2021-01-01", 30) == 28


def test_el_desplazamiento_hace_que_la_primera_ventana_empiece_en_t():
    offset = window_offset_days("2021-01-01", 30)
    # Las ventanas de Spark empiezan en 1970-01-01 + offset + k * 30 días
    starts = [EPOCH + timedelta(days=offset + 30 * k) for k in range(618, 623)]
    assert T in starts


def test_con_ventanas_de_7_dias_el_desplazamiento_es_otro():
    assert window_offset_days("2021-01-01", 7) == 18628 % 7


def test_window_id_es_estable_y_solo_depende_de_la_celda_y_el_inicio():
    assert window_id("dr4e3x", T) == "dr4e3x|2021-01-01"
    assert window_id("dr4e3x", T.replace(hour=5)) == "dr4e3x|2021-01-01"


def test_ventana_anterior_es_30_dias_antes():
    assert previous_window_start(T, 30) == datetime(2020, 12, 2)


def test_parse_day_y_from_epoch_seconds():
    assert parse_day("2021-01-01") == T
    assert from_epoch_seconds(seconds(T)) == T


# --- porcentajes ------------------------------------------------------------------------------


def test_porcentaje_negativo():
    assert percent(15, 60) == pytest.approx(25.0)


def test_porcentaje_sin_resenas_no_esta_definido():
    assert percent(0, 0) is None


def test_error_estandar_con_20_resenas_llega_a_11_puntos():
    # Justifica MIN_REVIEWS = 20: con p = 50 % y n = 20, el error estándar es ~11,2 puntos
    assert standard_error_pp(50, 20) == pytest.approx(11.18, abs=0.01)


def test_error_estandar_baja_con_mas_resenas():
    assert standard_error_pp(50, 200) < standard_error_pp(50, 20)


# --- regla de hotspot -------------------------------------------------------------------------

PREVIOUS = {"n_reviews": 50, "pct_negative": 20.0}


def test_sube_mas_que_el_umbral_es_hotspot():
    info = hotspot_decision(60, 45.0, PREVIOUS, threshold_pp=20.0, min_reviews=20)
    assert info["is_hotspot"] is True
    assert info["delta_pp"] == pytest.approx(25.0)
    assert info["hotspot_reason"] == "hotspot"


def test_justo_en_el_umbral_cuenta_como_hotspot():
    assert hotspot_decision(60, 40.0, PREVIOUS, 20.0, 20)["is_hotspot"] is True


def test_sube_menos_que_el_umbral_no_es_hotspot():
    info = hotspot_decision(60, 39.9, PREVIOUS, 20.0, 20)
    assert info["is_hotspot"] is False
    assert info["hotspot_reason"] == "bajo_umbral"


def test_una_bajada_nunca_es_hotspot():
    info = hotspot_decision(60, 5.0, PREVIOUS, 20.0, 20)
    assert info["is_hotspot"] is False
    assert info["delta_pp"] == pytest.approx(-15.0)


def test_sin_ventana_previa_no_hay_hotspot():
    info = hotspot_decision(60, 90.0, None, 20.0, 20)
    assert info["is_hotspot"] is False
    assert info["hotspot_reason"] == "sin_ventana_previa"
    assert info["delta_pp"] is None


def test_con_pocas_resenas_el_salto_es_ruido():
    info = hotspot_decision(19, 90.0, PREVIOUS, 20.0, 20)
    assert info["is_hotspot"] is False
    assert info["hotspot_reason"] == "pocas_resenas"
    assert info["delta_pp"] == pytest.approx(70.0)  # se informa igualmente


def test_con_pocas_resenas_en_la_ventana_previa_tampoco():
    info = hotspot_decision(60, 90.0, {"n_reviews": 5, "pct_negative": 0.0}, 20.0, 20)
    assert info["is_hotspot"] is False
    assert info["hotspot_reason"] == "pocas_resenas_previa"


# --- documentos de un micro-lote --------------------------------------------------------------


def test_un_documento_trae_geometria_de_la_celda_y_porcentajes():
    [doc] = build_window_docs([row(n=40, negative=10, stars_negative=8)], {}, threshold_pp=20.0)
    assert doc["_id"] == "dr4e3x|2021-01-01"
    assert doc["window_start"] == T
    assert doc["window_end"] == T + timedelta(days=30)
    assert doc["pct_negative"] == pytest.approx(25.0)
    assert doc["pct_negative_stars"] == pytest.approx(20.0)
    assert doc["geometry"]["type"] == "Polygon"
    ring = doc["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 5
    assert doc["centroid"]["type"] == "Point"


def test_la_ventana_previa_se_busca_primero_en_el_propio_lote():
    prev_start = T - timedelta(days=30)
    rows = [row(start=prev_start, n=40, negative=8), row(start=T, n=40, negative=24)]
    docs = build_window_docs(rows, {}, threshold_pp=20.0, min_reviews=20)
    assert [d["window_start"] for d in docs] == [prev_start, T]  # salen ordenadas por fecha
    assert docs[0]["hotspot_reason"] == "sin_ventana_previa"
    assert docs[1]["prev_pct_negative"] == pytest.approx(20.0)
    assert docs[1]["delta_pp"] == pytest.approx(40.0)
    assert docs[1]["is_hotspot"] is True


def test_si_la_previa_no_esta_en_el_lote_se_usa_la_guardada():
    stored = {"dr4e3x|2020-12-02": {"n_reviews": 50, "pct_negative": 10.0}}
    [doc] = build_window_docs([row(start=T, n=40, negative=20)], stored, threshold_pp=20.0, min_reviews=20)
    assert doc["prev_pct_negative"] == pytest.approx(10.0)
    assert doc["is_hotspot"] is True


def test_celdas_distintas_no_se_mezclan_como_previas():
    stored = {"9q8yyk|2020-12-02": {"n_reviews": 50, "pct_negative": 0.0}}
    [doc] = build_window_docs([row(geohash="dr4e3x", start=T)], stored, threshold_pp=20.0)
    assert doc["hotspot_reason"] == "sin_ventana_previa"


def test_ids_de_ventanas_previas_que_faltan_en_el_lote():
    rows = [row(start=T), row(start=T - timedelta(days=30)), row(geohash="9q8yyk", start=T)]
    # La previa de dr4e3x|T ya viene en el lote; hay que leer la de dr4e3x|T-30 y la de 9q8yyk|T
    assert missing_previous_ids(rows, 30) == {"dr4e3x|2020-11-02", "9q8yyk|2020-12-02"}


# --- calibración del umbral -------------------------------------------------------------------


def test_cuantil_con_interpolacion_lineal():
    assert quantile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
    assert quantile([1, 2, 3, 4], 0.0) == 1
    assert quantile([1, 2, 3, 4], 1.0) == 4
    assert quantile(list(range(101)), 0.95) == pytest.approx(95.0)


def test_cuantil_sin_datos_o_fuera_de_rango():
    assert quantile([], 0.5) is None
    with pytest.raises(ValueError):
        quantile([1, 2], 1.5)


def test_el_umbral_es_el_percentil_95_de_las_variaciones():
    deltas = [float(d) for d in range(-50, 51)]  # 101 variaciones de -50 a 50
    assert calibrate_threshold(deltas, 0.95) == pytest.approx(45.0)


def test_el_umbral_nunca_es_negativo():
    assert calibrate_threshold([-10.0, -8.0, -5.0], 0.95) == 0.0


def test_calibrar_sin_pares_devuelve_none():
    assert calibrate_threshold([]) is None


def test_resumen_de_la_distribucion():
    resumen = summarize_deltas([-2.0, 0.0, 2.0])
    assert resumen["n_pairs"] == 3
    assert resumen["mean"] == pytest.approx(0.0)
    assert resumen["std"] == pytest.approx(2.0)
    assert resumen["p50"] == pytest.approx(0.0)
    assert resumen["max"] == 2.0


def test_resumen_sin_datos():
    assert summarize_deltas([]) == {"n_pairs": 0}
