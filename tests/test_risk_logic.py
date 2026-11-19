"""Modelo de riesgo de cierre (spark_batch/risk_logic.py), sin Spark ni MongoDB."""

from datetime import datetime

import pytest

from risk_logic import (
    FEATURES,
    add_months,
    choose_threshold,
    competitors_pipeline,
    confusion_at,
    in_population,
    mean_sentiment,
    metrics_at_threshold,
    negative_trend,
    prevalence,
    risk_label,
)

T = datetime(2021, 1, 1)


# --- meses ------------------------------------------------------------------------------------


def test_sumar_meses_cruza_anos():
    assert add_months(T, 12) == datetime(2022, 1, 1)
    assert add_months(T, -3) == datetime(2020, 10, 1)
    assert add_months(T, -6) == datetime(2020, 7, 1)


def test_sumar_meses_ajusta_el_dia_si_no_existe():
    assert add_months(datetime(2021, 1, 31), 1) == datetime(2021, 2, 28)
    assert add_months(datetime(2020, 1, 31), 1) == datetime(2020, 2, 29)  # bisiesto


# --- población y etiqueta (definición literal de la guía) -------------------------------------


def test_poblacion_existia_en_t_y_tuvo_actividad_despues():
    assert in_population(datetime(2018, 5, 1), datetime(2021, 6, 1), T) is True


def test_no_esta_en_la_poblacion_si_no_tuvo_actividad_desde_t():
    assert in_population(datetime(2018, 5, 1), datetime(2020, 12, 31), T) is False


def test_no_esta_en_la_poblacion_si_no_existia_antes_de_t():
    assert in_population(datetime(2021, 3, 1), datetime(2021, 9, 1), T) is False


def test_cerrado_con_ultima_resena_dentro_de_12_meses_es_positivo():
    assert risk_label(is_open=0, last_review=datetime(2021, 8, 15), cutoff=T) == 1


def test_el_limite_de_12_meses_es_inclusivo():
    assert risk_label(0, datetime(2022, 1, 1), T) == 1
    assert risk_label(0, datetime(2022, 1, 2), T) == 0


def test_cerrado_pero_con_actividad_despues_del_plazo_es_negativo():
    assert risk_label(is_open=0, last_review=datetime(2022, 1, 15), cutoff=T) == 0


def test_abierto_es_negativo_aunque_su_ultima_resena_caiga_en_el_plazo():
    assert risk_label(is_open=1, last_review=datetime(2021, 6, 1), cutoff=T) == 0


def test_sin_actividad_despues_de_t_queda_excluido():
    assert risk_label(is_open=0, last_review=datetime(2020, 12, 31), cutoff=T) is None


def test_una_resena_justo_en_t_cuenta_como_actividad():
    assert risk_label(is_open=0, last_review=T, cutoff=T) == 1


# --- variables --------------------------------------------------------------------------------


def test_sentimiento_medio_entre_menos_uno_y_uno():
    assert mean_sentiment(n_positive=6, n_negative=2, n_reviews=10) == pytest.approx(0.4)
    assert mean_sentiment(0, 10, 10) == pytest.approx(-1.0)
    assert mean_sentiment(10, 0, 10) == pytest.approx(1.0)


def test_sentimiento_medio_sin_resenas_no_esta_definido():
    assert mean_sentiment(0, 0, 0) is None


def test_tendencia_positiva_si_empeora():
    # 3 meses recientes: 6 de 10 negativas (60 %); 3 anteriores: 2 de 10 (20 %) -> +40 puntos
    assert negative_trend(6, 10, 2, 10) == pytest.approx(40.0)


def test_tendencia_negativa_si_mejora():
    assert negative_trend(1, 10, 5, 10) == pytest.approx(-40.0)


def test_tendencia_sin_resenas_suficientes_es_cero():
    assert negative_trend(3, 4, 0, 20) == 0.0  # solo 4 reseñas recientes: ruido
    assert negative_trend(0, 0, 0, 0) == 0.0


def test_las_variables_son_las_seis_de_la_guia():
    assert FEATURES == ["mean_sentiment", "neg_trend_6m", "stars_mean", "n_reviews", "age_days", "competitors_500m"]


# --- competidores con $geoNear ----------------------------------------------------------------


def test_pipeline_geonear_a_500_m_de_la_misma_categoria_sin_contar_al_propio_negocio():
    pipeline = competitors_pipeline(-75.16, 39.95, "Pizza", "abc")
    geo_near = pipeline[0]["$geoNear"]
    assert geo_near["maxDistance"] == 500
    assert geo_near["spherical"] is True
    assert geo_near["near"] == {"type": "Point", "coordinates": [-75.16, 39.95]}
    assert geo_near["query"] == {"primary_category": "Pizza", "business_id": {"$ne": "abc"}}
    assert pipeline[1] == {"$count": "competitors"}


# --- umbral y métricas ------------------------------------------------------------------------


def test_matriz_de_confusion_en_un_umbral():
    scores = [0.9, 0.8, 0.3, 0.2, 0.1]
    labels = [1, 0, 1, 0, 0]
    assert confusion_at(scores, labels, 0.5) == (1, 1, 1, 2)  # tp, fp, fn, tn


def test_precision_recall_y_f1_en_un_umbral():
    m = metrics_at_threshold([0.9, 0.8, 0.3, 0.2, 0.1], [1, 0, 1, 0, 0], 0.5)
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["f1"] == pytest.approx(0.5)
    assert m["alert_rate"] == pytest.approx(2 / 5)


def test_sin_alertas_la_precision_es_cero_y_no_falla():
    m = metrics_at_threshold([0.1, 0.2], [1, 0], 0.9)
    assert m["precision"] == 0.0 and m["recall"] == 0.0 and m["f1"] == 0.0


def test_el_umbral_elegido_maximiza_el_f1():
    scores = [0.95, 0.90, 0.80, 0.40, 0.30, 0.20, 0.10]
    labels = [1, 1, 1, 0, 1, 0, 0]
    umbral = choose_threshold(scores, labels)
    mejor = metrics_at_threshold(scores, labels, umbral)["f1"]
    for candidato in scores:
        assert metrics_at_threshold(scores, labels, candidato)["f1"] <= mejor + 1e-12
    assert umbral == 0.30  # tp=4, fp=1 -> precision 0,8, recall 1,0, F1 0,889


def test_los_empates_de_puntuacion_entran_juntos():
    # Dos negocios con la misma puntuación: no se puede alertar a uno y al otro no
    assert choose_threshold([0.5, 0.5, 0.1], [1, 0, 0]) == 0.5


def test_sin_positivos_no_hay_umbral():
    assert choose_threshold([0.1, 0.2], [0, 0]) is None
    assert choose_threshold([], []) is None


def test_prevalencia_es_el_auc_pr_de_no_saber_nada():
    assert prevalence([1, 0, 0, 0]) == pytest.approx(0.25)
    assert prevalence([]) is None
