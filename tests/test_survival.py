"""Curvas de supervivencia de Kaplan-Meier (spark_batch/survival.py), sin Spark ni MongoDB."""

import random
from datetime import datetime

import pytest

from survival import (
    bounding_polygon,
    business_record,
    kaplan_meier,
    meets_min,
    primary_category,
    survival_at,
    window_start_datetime,
    years,
)

# Ejemplo clásico (Freireich, grupo 6-MP, 21 pacientes, 9 recaídas). Respuestas de libro de texto:
# S(6)=0,857  S(7)=0,807  S(10)=0,753  S(13)=0,690  S(16)=0,627  S(22)=0,538  S(23)=0,448  mediana=23
FREIREICH = [(6, 1)] * 3 + [(7, 1), (10, 1), (13, 1), (16, 1), (22, 1), (23, 1)] + [
    (6, 0), (9, 0), (10, 0), (11, 0), (17, 0), (19, 0), (20, 0), (25, 0), (32, 0), (32, 0), (34, 0), (35, 0),
]  # fmt: skip


def records(pairs):
    return [(0, t, e) for t, e in pairs]


def test_ejemplo_de_libro_de_texto_sin_entrada_tardia():
    km = kaplan_meier(records(FREIREICH))
    esperado = {6: 0.857, 7: 0.807, 10: 0.753, 13: 0.690, 16: 0.627, 22: 0.538, 23: 0.448}
    for t, s in esperado.items():
        assert survival_at(km["curve"], t) == pytest.approx(s, abs=0.001), t
    assert km["median"] == 23
    assert (km["n"], km["n_events"], km["n_censored"]) == (21, 9, 12)


def test_numero_en_riesgo_del_ejemplo_de_libro():
    curva = {p["t"]: p for p in kaplan_meier(records(FREIREICH))["curve"]}
    assert curva[6]["n_risk"] == 21 and curva[6]["n_events"] == 3 and curva[6]["n_censored"] == 1
    assert curva[7]["n_risk"] == 17
    assert curva[10]["n_risk"] == 15 and curva[10]["n_censored"] == 1
    assert curva[23]["n_risk"] == 6


def test_todos_censurados_no_hay_curva_ni_mediana():
    km = kaplan_meier(records([(5, 0), (10, 0), (20, 0)]))
    assert km["curve"] == []
    assert km["median"] is None
    assert survival_at(km["curve"], 100) == 1.0


def test_sin_datos():
    km = kaplan_meier([])
    assert km["n"] == 0 and km["curve"] == [] and km["median"] is None


def test_la_mediana_no_existe_si_la_curva_no_baja_de_0_5():
    # 1 cierre entre 10 negocios: S = 0,9 y nunca llega a 0,5
    km = kaplan_meier(records([(5, 1)] + [(30, 0)] * 9))
    assert km["median"] is None
    assert survival_at(km["curve"], 5) == pytest.approx(0.9)


# --- entrada tardía ---------------------------------------------------------------------------


def test_entrada_tardia_cuenta_solo_a_quien_ya_esta_en_riesgo():
    # A: entra en 0, cierra en 5. B: entra en 3, cierra en 8. C: entra en 6, censurado en 10.
    km = kaplan_meier([(0, 5, 1), (3, 8, 1), (6, 10, 0)])
    curva = {p["t"]: p for p in km["curve"]}
    assert curva[5]["n_risk"] == 2  # A y B; C todavía no ha entrado
    assert curva[5]["survival"] == pytest.approx(0.5)
    assert curva[8]["n_risk"] == 2  # B y C; A ya cerró
    assert curva[8]["survival"] == pytest.approx(0.25)
    assert km["n_late_entry"] == 2


def test_sin_entrada_tardia_el_mismo_caso_da_otra_curva():
    # Contar a B y C desde la edad 0 los metería en el riesgo de t=5 y subiría la supervivencia
    km = kaplan_meier([(0, 5, 1), (0, 8, 1), (0, 10, 0)])
    assert survival_at(km["curve"], 5) == pytest.approx(2 / 3)


def test_un_registro_que_sale_antes_de_entrar_se_ignora():
    km = kaplan_meier([(0, 5, 1), (10, 10, 1), (10, 7, 1)])
    assert km["n"] == 1


def test_el_numero_en_riesgo_no_cuenta_a_quien_ya_salio():
    km = kaplan_meier([(0, 2, 0), (0, 4, 1), (0, 6, 1)])
    assert {p["t"]: p["n_risk"] for p in km["curve"]} == {4: 2, 6: 1}


# --- propiedades de la curva ------------------------------------------------------------------


def test_la_curva_es_monotona_y_esta_entre_0_y_1_con_datos_aleatorios():
    rng = random.Random(7)
    datos = []
    for _ in range(500):
        entrada = rng.choice([0, 0, 0, rng.randint(1, 300)])
        datos.append((entrada, entrada + rng.randint(1, 800), rng.randint(0, 1)))
    curva = kaplan_meier(datos)["curve"]
    valores = [p["survival"] for p in curva]
    assert valores == sorted(valores, reverse=True)
    assert all(0 <= v <= 1 for v in valores)
    assert all(p["ci_low"] <= p["survival"] <= p["ci_high"] for p in curva)
    assert all(p["n_risk"] >= p["n_events"] for p in curva)


def test_intervalo_de_confianza_de_greenwood_log_log():
    # n=10, un cierre en t=1: S=0,9; Greenwood = 1/(10*9). IC 95 % por log-log: [0,473, 0,985]
    km = kaplan_meier(records([(1, 1)] + [(5, 0)] * 9))
    punto = km["curve"][0]
    assert punto["survival"] == pytest.approx(0.9)
    assert punto["ci_low"] == pytest.approx(0.473, abs=0.001)
    assert punto["ci_high"] == pytest.approx(0.985, abs=0.001)


def test_si_cierran_todos_la_supervivencia_llega_a_cero():
    km = kaplan_meier(records([(1, 1), (2, 1)]))
    assert km["curve"][-1]["survival"] == 0.0
    assert km["median"] == 1


# --- registro de un negocio -------------------------------------------------------------------

W0 = datetime(2010, 1, 1)


def test_negocio_nuevo_entra_en_cero():
    registro = business_record(datetime(2012, 1, 1), datetime(2014, 1, 1), is_open=0, window_start=W0)
    assert registro == (0, 731, 1)


def test_negocio_que_ya_existia_entra_con_su_edad_en_w0():
    registro = business_record(datetime(2008, 1, 1), datetime(2012, 1, 1), is_open=1, window_start=W0)
    entrada, duracion, evento = registro
    assert entrada == (W0 - datetime(2008, 1, 1)).days
    assert duracion == (datetime(2012, 1, 1) - datetime(2008, 1, 1)).days
    assert evento == 0  # abierto = censurado


def test_negocio_que_termino_antes_de_la_ventana_no_se_observa():
    assert business_record(datetime(2005, 1, 1), datetime(2008, 6, 1), is_open=0, window_start=W0) is None


def test_la_vida_minima_es_un_dia():
    assert business_record(datetime(2015, 5, 1), datetime(2015, 5, 1), is_open=1, window_start=W0) == (0, 1, 0)


# --- grupos y zonas ---------------------------------------------------------------------------


def test_un_grupo_pequeno_no_permite_conclusiones():
    assert meets_min(100, 20) is True
    assert meets_min(99, 50) is False
    assert meets_min(500, 19) is False


def test_poligono_de_zona_cerrado_y_recortando_atipicos():
    coords = [(-75.0 + i * 0.001, 40.0 + i * 0.001) for i in range(100)] + [(10.0, 10.0)]  # un punto absurdo
    poligono = bounding_polygon(coords, low=0.0, high=0.98, pad=0.0)
    anillo = poligono["coordinates"][0]
    assert anillo[0] == anillo[-1] and len(anillo) == 5
    oeste, este = anillo[0][0], anillo[1][0]
    assert oeste == pytest.approx(-75.0) and este < -74.8  # el punto en (10, 10) quedó fuera


def test_conversiones_auxiliares():
    assert years(365.25) == pytest.approx(1.0)
    assert years(None) is None
    assert window_start_datetime("2010-01-01") == W0


def test_categoria_principal_es_la_primera_de_la_lista():
    assert primary_category("Pizza, Restaurants, Italian") == "Pizza"
    assert primary_category("  Bars  ,Nightlife") == "Bars"


def test_sin_categorias_cae_en_sin_categoria():
    assert primary_category(None) == "Sin categoría"
    assert primary_category("") == "Sin categoría"
    assert primary_category(" , Food") == "Sin categoría"
