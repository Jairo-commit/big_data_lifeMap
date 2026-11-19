"""Endpoints nuevos de la API (api_flask/live.py y kafka_monitor.py), sin Flask, MongoDB ni Kafka."""

import threading
from datetime import datetime

import pytest

from kafka_monitor import KafkaMonitor
from live import (
    ALERT_COLUMNS,
    CURVE_COLUMNS,
    HOTSPOT_COLUMNS,
    RISK_COLUMNS,
    alert_row,
    alerts_query,
    circle_filter,
    evolution_pipeline,
    evolution_row,
    hotspot_row,
    hotspots_query,
    lag_by_partition,
    parse_format,
    parse_optional_circle,
    parse_state,
    parse_survival_kind,
    parse_window,
    risk_near_query,
    risk_row,
    survival_curve_rows,
    survival_summary,
    to_csv,
)
from queries import EARTH_RADIUS_M, BadRequest
from sentiment import overall_status

W = datetime(2021, 6, 30)


# --- parámetros --------------------------------------------------------------------------------------


def test_formato_por_defecto_json_y_csv_valido():
    assert parse_format({}) == "json"
    assert parse_format({"format": "CSV"}) == "csv"


def test_formato_desconocido_se_rechaza():
    with pytest.raises(BadRequest):
        parse_format({"format": "xml"})


def test_ventana_latest_por_defecto_o_una_fecha():
    assert parse_window({}) is None
    assert parse_window({"window": "latest"}) is None
    assert parse_window({"window": "2021-06-30"}) == W


@pytest.mark.parametrize("value", ["junio", "2021-13-40", "30/06/2021"])
def test_ventana_invalida(value):
    with pytest.raises(BadRequest):
        parse_window({"window": value})


def test_circulo_opcional_sin_lat_ni_lon_es_none():
    assert parse_optional_circle({}) is None


def test_circulo_con_radio_por_defecto():
    assert parse_optional_circle({"lat": "39.95", "lon": "-75.16"}) == (-75.16, 39.95, 5000.0)
    assert parse_optional_circle({"lat": "39.95", "lon": "-75.16", "radius": "800"})[2] == 800.0


def test_circulo_incompleto_o_fuera_de_rango():
    with pytest.raises(BadRequest):
        parse_optional_circle({"lat": "39.95"})
    with pytest.raises(BadRequest):
        parse_optional_circle({"lon": "-75.16"})
    with pytest.raises(BadRequest):
        parse_optional_circle({"lat": "91", "lon": "0"})
    with pytest.raises(BadRequest):
        parse_optional_circle({"lat": "0", "lon": "0", "radius": "999999"})


def test_estado_de_alertas_y_tipo_de_supervivencia():
    assert parse_state({}) == "active"
    assert parse_state({"state": "ALL"}) == "all"
    assert parse_survival_kind({}) == "category"
    assert parse_survival_kind({"by": "zone"}) == "zone"
    with pytest.raises(BadRequest):
        parse_state({"state": "viejas"})
    with pytest.raises(BadRequest):
        parse_survival_kind({"by": "ciudad"})


# --- consultas de MongoDB -----------------------------------------------------------------------------


def test_circulo_en_radianes():
    filtro = circle_filter("centroid", (-75.16, 39.95, 1000.0))
    esfera = filtro["centroid"]["$geoWithin"]["$centerSphere"]
    assert esfera[0] == [-75.16, 39.95]
    assert esfera[1] == pytest.approx(1000.0 / EARTH_RADIUS_M)


def test_hotspots_de_una_ventana_con_y_sin_radio():
    assert hotspots_query(W) == {"is_hotspot": True, "window_start": W}
    con_radio = hotspots_query(W, (-75.16, 39.95, 2000.0))
    assert con_radio["is_hotspot"] is True and con_radio["window_start"] == W
    assert "$centerSphere" in con_radio["centroid"]["$geoWithin"]


def test_alertas_por_estado_probabilidad_y_zona():
    assert alerts_query("active") == {"active": True}
    assert alerts_query("cleared") == {"active": False}
    assert alerts_query("all") == {}
    assert alerts_query("active", min_probability=0.7)["probability"] == {"$gte": 0.7}
    assert "$centerSphere" in alerts_query("all", circle=(0.0, 0.0, 100.0))["geometry"]["$geoWithin"]
    poligono = {"type": "Polygon", "coordinates": []}
    assert alerts_query("all", geometry=poligono)["geometry"] == {"$geoWithin": {"$geometry": poligono}}


def test_riesgo_cerca_usa_near_y_probabilidad_minima():
    q = risk_near_query(-75.16, 39.95, 1500.0, 0.5)
    assert q["location"]["$near"]["$maxDistance"] == 1500.0
    assert q["location"]["$near"]["$geometry"] == {"type": "Point", "coordinates": [-75.16, 39.95]}
    assert q["risk_probability"] == {"$gte": 0.5}
    assert "risk_probability" not in risk_near_query(0.0, 0.0, 1.0)


def test_evolucion_agrupa_por_ventana_y_filtra_por_radio_solo_si_se_pide():
    sin_radio = evolution_pipeline()
    assert sin_radio[0]["$group"]["_id"] == "$window_start"
    assert sin_radio[-1] == {"$sort": {"_id": 1}}
    con_radio = evolution_pipeline((-75.16, 39.95, 2000.0))
    assert "$match" in con_radio[0] and len(con_radio) == len(sin_radio) + 1


# --- filas planas -------------------------------------------------------------------------------------


def test_fila_de_hotspot_con_centroide_y_fechas_iso():
    doc = {
        "geohash": "dhvqdt",
        "window_start": W,
        "window_end": datetime(2021, 7, 30),
        "n_reviews": 26,
        "pct_negative": 57.7,
        "prev_pct_negative": 23.8,
        "delta_pp": 33.9,
        "centroid": {"type": "Point", "coordinates": [-82.45, 27.95]},
    }
    fila = hotspot_row(doc)
    assert fila["window_start"] == "2021-06-30T00:00:00"
    assert (fila["lat"], fila["lon"]) == (27.95, -82.45)
    assert fila["delta_pp"] == 33.9


def test_fila_de_alerta_aplana_las_variables():
    doc = {
        "business_id": "b1",
        "probability": 0.8,
        "active": True,
        "alert_date": W,
        "geometry": {"type": "Point", "coordinates": [-75.16, 39.95]},
        "features": {"mean_sentiment": 0.4, "n_reviews": 12.0},
    }
    fila = alert_row(doc)
    assert (fila["lat"], fila["lon"]) == (39.95, -75.16)
    assert fila["mean_sentiment"] == 0.4 and fila["n_reviews"] == 12.0
    assert fila["alert_date"] == "2021-06-30T00:00:00"
    assert fila["cleared_date"] is None


def test_fila_de_riesgo():
    doc = {"business_id": "b1", "risk_probability": 0.4, "risk_flag": False, "location": {"coordinates": [-90.1, 30.0]}}
    fila = risk_row(doc)
    assert (fila["lat"], fila["lon"]) == (30.0, -90.1) and fila["risk_probability"] == 0.4


def test_evolucion_calcula_el_porcentaje_negativo_ponderado():
    fila = evolution_row(
        {"_id": W, "n_reviews": 200, "n_negative": 50, "n_negative_stars": 40, "n_cells": 3, "n_hotspots": 1}
    )
    assert fila["pct_negative"] == pytest.approx(25.0)
    assert fila["pct_negative_stars"] == pytest.approx(20.0)
    assert evolution_row({"_id": W, "n_reviews": 0, "n_negative": 0, "n_negative_stars": 0})["pct_negative"] is None


def test_curva_de_supervivencia_como_filas_con_anos():
    doc = {
        "group": "Pizza",
        "kind": "category",
        "curve_fields": ["t", "n_risk", "n_events", "n_censored", "survival", "ci_low", "ci_high"],
        "curve": [[365, 100, 2, 1, 0.98, 0.94, 0.99], [730, 90, 3, 0, 0.95, 0.9, 0.97]],
        "n_businesses": 100,
        "window_start": datetime(2010, 1, 1),
    }
    filas = survival_curve_rows(doc)
    assert len(filas) == 2 and filas[0]["group"] == "Pizza" and filas[1]["survival"] == 0.95
    assert filas[0]["t_years"] == pytest.approx(365 / 365.25)
    resumen = survival_summary(doc)
    assert resumen["n_businesses"] == 100 and resumen["window_start"] == "2010-01-01T00:00:00"


def test_las_columnas_fijas_cubren_lo_que_dicen_las_filas():
    assert {"geohash", "delta_pp", "lat", "lon"} <= set(HOTSPOT_COLUMNS)
    assert {"probability", "active", "lat", "lon", "mean_sentiment"} <= set(ALERT_COLUMNS)
    assert {"risk_probability", "distance_m"} <= set(RISK_COLUMNS)
    assert {"t", "n_risk", "survival", "ci_low", "ci_high"} <= set(CURVE_COLUMNS)


# --- CSV ----------------------------------------------------------------------------------------------


def test_csv_con_encabezado_vacios_y_fechas_iso():
    texto = to_csv([{"a": 1, "b": None, "c": W}, {"a": 2, "b": "x", "c": None}], ["a", "b", "c"])
    assert texto.splitlines() == ["a,b,c", "1,,2021-06-30T00:00:00", "2,x,"]


def test_csv_sin_filas_lleva_el_encabezado_de_las_columnas_fijas():
    assert to_csv([], ["a", "b"]).splitlines() == ["a,b"]


def test_csv_ignora_columnas_de_mas():
    assert to_csv([{"a": 1, "geometry": {"x": 1}}], ["a"]).splitlines() == ["a", "1"]


# --- retraso del consumidor ---------------------------------------------------------------------------


def test_retraso_por_particion_y_total():
    lag = lag_by_partition({"0": 100, "1": 50}, {"0": 90, "1": 50})
    assert lag == {"partitions": {"0": 10, "1": 0}, "total": 10}


def test_retraso_nunca_es_negativo_y_una_particion_sin_avance_cuenta_todo():
    assert lag_by_partition({"0": 10}, {"0": 99})["total"] == 0
    assert lag_by_partition({"0": 10, "1": 7}, {"0": 10})["partitions"] == {"0": 0, "1": 7}


def test_sin_avance_no_se_sabe_el_retraso():
    assert lag_by_partition({"0": 10}, {}) is None
    assert lag_by_partition({"0": 10}, None) is None


# --- monitor de Kafka ---------------------------------------------------------------------------------


class Reloj:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def monitor(probe, progress=dict, bootstrap="kafka:9092", clock=None, probe_timeout=2.0):
    return KafkaMonitor(
        bootstrap, "reviews", probe, progress, stale_after=60.0, probe_timeout=probe_timeout, clock=clock or Reloj()
    )


def test_sin_bootstrap_kafka_no_esta_configurado_y_no_se_sondea():
    m = monitor(lambda *_: pytest.fail("no debe sondear"), bootstrap="")
    assert m.snapshot() == {"status": "not_configured"}
    assert m.start() is None


def test_antes_del_primer_sondeo_el_estado_es_desconocido():
    assert monitor(lambda *_: {"0": 1}).snapshot()["status"] == "unknown"


def test_foto_con_offsets_finales_y_retraso_de_cada_consumidor():
    m = monitor(
        lambda *_: {"0": 100, "1": 200},
        progress=lambda: {"streaming_alerts": {"0": 90, "1": 200}, "streaming_inference": {}},
    )
    m.refresh()
    foto = m.snapshot()
    assert foto["status"] == "healthy" and foto["end_offsets"] == {"0": 100, "1": 200}
    assert foto["consumers"]["streaming_alerts"] == {"partitions": {"0": 10, "1": 0}, "total": 10}
    assert foto["consumers"]["streaming_inference"] == {"status": "unknown"}


def test_un_fallo_del_broker_queda_como_unreachable_sin_propagarse():
    def caido(*_):
        raise ConnectionError("sin broker")

    m = monitor(caido)
    m.refresh()
    assert m.snapshot()["status"].startswith("unreachable: sin broker")


def test_un_fallo_leyendo_el_avance_no_tumba_el_estado_del_broker():
    def roto():
        raise RuntimeError("mongo")

    m = monitor(lambda *_: {"0": 5}, progress=roto)
    m.refresh()
    assert m.snapshot()["status"] == "healthy" and m.snapshot()["consumers"] == {}


def test_si_el_hilo_deja_de_actualizar_el_estado_pasa_a_stale():
    reloj = Reloj()
    m = monitor(lambda *_: {"0": 5}, clock=reloj)
    m.refresh()
    reloj.now = 30
    assert m.snapshot()["status"] == "healthy"
    reloj.now = 61
    assert m.snapshot()["status"] == "stale"


# --- estado general de /health ------------------------------------------------------------------------


@pytest.mark.parametrize("kafka", ["not_configured", "unknown", "healthy"])
def test_kafka_sano_no_configurado_o_sin_sondear_no_degrada(kafka):
    assert overall_status("healthy", "loaded", kafka) == "ok"


@pytest.mark.parametrize("kafka", ["unreachable: timeout", "stale", "error: x"])
def test_kafka_configurado_y_caido_degrada(kafka):
    assert overall_status("healthy", "loaded", kafka) == "degraded"


def test_sin_argumento_de_kafka_se_comporta_como_antes():
    assert overall_status("healthy", "not_trained") == "ok"
    assert overall_status("unhealthy: x", "loaded") == "degraded"


def test_un_sondeo_que_se_cuelga_se_da_por_caido_al_cumplirse_el_plazo():
    liberar = threading.Event()
    llamadas = []

    def colgado(*_):
        llamadas.append(1)
        liberar.wait(5)  # como kafka-python reintentando la conexión con el broker apagado
        return {"0": 5}

    m = monitor(colgado, probe_timeout=0.2)
    m.refresh()
    assert m.snapshot()["status"].startswith("unreachable: Kafka no respondió")
    liberar.set()


def test_mientras_un_sondeo_siga_colgado_no_se_lanzan_mas():
    liberar = threading.Event()
    llamadas = []

    def colgado(*_):
        llamadas.append(1)
        liberar.wait(5)
        return {"0": 5}

    m = monitor(colgado, probe_timeout=0.2)
    m.refresh()
    m.refresh()
    m.refresh()
    assert len(llamadas) == 1  # un solo hilo colgado, no tres
    assert "sigue sin responder" in m.snapshot()["status"]
    liberar.set()


def test_cuando_el_broker_vuelve_el_siguiente_sondeo_lo_recupera():
    liberar = threading.Event()
    estado = {"caido": True}

    def sondeo(*_):
        if estado["caido"]:
            liberar.wait(5)
        return {"0": 9}

    m = monitor(sondeo, probe_timeout=0.2)
    m.refresh()
    assert m.snapshot()["status"].startswith("unreachable")
    estado["caido"] = False
    liberar.set()
    m._probe_thread.join(2)  # el hilo colgado termina al volver el broker
    m.refresh()
    assert m.snapshot()["status"] == "healthy" and m.snapshot()["end_offsets"] == {"0": 9}
