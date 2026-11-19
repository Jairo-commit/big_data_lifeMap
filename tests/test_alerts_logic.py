"""Alertas de riesgo en streaming (spark_batch/alerts_logic.py), sin Spark ni MongoDB."""

import random
from datetime import datetime, timedelta

import pytest

from alerts_logic import (
    alert_action,
    build_alert,
    features_at,
    latest_date,
    merge_reviews,
    next_offsets,
    pre_window_start,
    sentiment_sign,
    trend_windows,
)
from risk_logic import FEATURES, add_months, negative_trend

T = datetime(2021, 1, 1)


# --- referencia: las variables recalculadas de cero con las fórmulas del entrenamiento ------------------


def pre_aggregates(reviews, business_id="b1", competitors=3):
    """Lo que guarda risk_features a T: agregados de las reseñas anteriores a T."""
    before = [(d, s) for d, s in reviews if d < T]
    n = len(before)
    return {
        "business_id": business_id,
        "n_reviews": n,
        "stars_mean": sum(s for _, s in before) / n,
        "mean_sentiment": sum(sentiment_sign(s) for _, s in before) / n,
        "first_review": min(d for d, _ in before),
        "competitors_500m": competitors,
        "location": {"type": "Point", "coordinates": [-75.16, 39.95]},
        "city": "Philadelphia",
        "primary_category": "Pizza",
    }


def from_scratch(reviews, t, competitors=3):
    """Variables al instante t calculadas directamente sobre todas las reseñas <= t (segunda implementación)."""
    upto = [(d, s) for d, s in reviews if d <= t]
    n = len(upto)
    recent_start, prev_start = add_months(t, -3), add_months(t, -6)
    recent = [s for d, s in upto if recent_start <= d <= t]
    previous = [s for d, s in upto if prev_start <= d < recent_start]
    first = min(d for d, _ in reviews if d < T)
    return {
        "mean_sentiment": sum(sentiment_sign(s) for _, s in upto) / n,
        "neg_trend_6m": negative_trend(
            sum(1 for s in recent if s <= 2), len(recent), sum(1 for s in previous if s <= 2), len(previous)
        ),
        "stars_mean": sum(s for _, s in upto) / n,
        "n_reviews": float(n),
        "age_days": float((t - first).days),
        "competitors_500m": float(competitors),
    }


def random_history(rng, n_pre=40, n_post=40):
    pre = [
        (T - timedelta(days=rng.randint(1, 500), seconds=rng.randint(0, 86399)), rng.randint(1, 5))
        for _ in range(n_pre)
    ]
    post = [
        (T + timedelta(days=rng.randint(0, 300), seconds=rng.randint(0, 86399)), rng.randint(1, 5))
        for _ in range(n_post)
    ]
    return pre, post


def pre_window(reviews, t):
    return [(d, s) for d, s in reviews if d < T and d >= pre_window_start(t)]


def assert_same(a, b):
    assert set(a) == set(FEATURES) == set(b)
    for name in FEATURES:
        assert a[name] == pytest.approx(b[name], abs=1e-9), name


# --- propiedad central: lote a lote == de cero ----------------------------------------------------------


@pytest.mark.parametrize("seed", range(25))
def test_aplicar_las_resenas_por_lotes_da_lo_mismo_que_recalcular_de_cero(seed):
    rng = random.Random(seed)
    pre_reviews, post_reviews = random_history(rng, n_pre=rng.randint(5, 60), n_post=rng.randint(1, 60))
    pre = pre_aggregates(pre_reviews)
    ordered = sorted((f"r{i}", d, s) for i, (d, s) in enumerate(post_reviews))
    ordered.sort(key=lambda r: r[1])

    state, position = [], 0
    while position < len(ordered):
        size = rng.randint(1, 7)
        batch = [list(r) for r in ordered[position : position + size]]
        position += size
        state = merge_reviews(state, batch)
        t = latest_date(state)
        got = features_at(pre, state, pre_window(pre_reviews, t), t)
        expected = from_scratch(pre_reviews + [(r[1], r[2]) for r in state], t)
        assert_same(got, expected)


def test_repetir_un_lote_no_cambia_nada():
    rng = random.Random(3)
    pre_reviews, post_reviews = random_history(rng)
    pre = pre_aggregates(pre_reviews)
    batch = [[f"r{i}", d, s] for i, (d, s) in enumerate(post_reviews)]
    once = merge_reviews([], batch)
    twice = merge_reviews(once, batch)
    assert once == twice
    t = latest_date(once)
    assert_same(
        features_at(pre, twice, pre_window(pre_reviews, t), t), features_at(pre, once, pre_window(pre_reviews, t), t)
    )


def test_sin_resenas_nuevas_se_reproducen_las_variables_a_t():
    rng = random.Random(11)
    pre_reviews, _ = random_history(rng, n_pre=80, n_post=0)
    pre = pre_aggregates(pre_reviews)
    got = features_at(pre, [], pre_window(pre_reviews, T), T)
    recent = [s for d, s in pre_reviews if T - timedelta(days=0) > d >= add_months(T, -3)]
    previous = [s for d, s in pre_reviews if add_months(T, -6) <= d < add_months(T, -3)]
    expected_trend = negative_trend(
        sum(s <= 2 for s in recent), len(recent), sum(s <= 2 for s in previous), len(previous)
    )
    assert got["neg_trend_6m"] == pytest.approx(expected_trend)
    assert got["n_reviews"] == pre["n_reviews"]
    assert got["stars_mean"] == pytest.approx(pre["stars_mean"])
    assert got["mean_sentiment"] == pytest.approx(pre["mean_sentiment"])
    assert got["age_days"] == (T - pre["first_review"]).days


def test_no_se_usan_resenas_posteriores_a_t():
    rng = random.Random(5)
    pre_reviews, post_reviews = random_history(rng, n_post=20)
    pre = pre_aggregates(pre_reviews)
    state = merge_reviews([], [[f"r{i}", d, s] for i, (d, s) in enumerate(post_reviews)])
    t = sorted(r[1] for r in state)[len(state) // 2]  # un instante a mitad de camino
    got = features_at(pre, state, pre_window(pre_reviews, t), t)
    assert got["n_reviews"] == pre["n_reviews"] + sum(1 for r in state if r[1] <= t)


# --- estado e idempotencia --------------------------------------------------------------------------------


def test_merge_ordena_por_fecha_y_no_duplica():
    a = ["a", datetime(2021, 3, 2), 5]
    b = ["b", datetime(2021, 3, 1), 1]
    assert merge_reviews([a], [b, list(a)]) == [b, a]


def test_si_un_id_se_repite_gana_la_resena_ya_guardada():
    guardada = ["a", datetime(2021, 3, 1), 5]
    repetida = ["a", datetime(2021, 3, 1), 1]
    assert merge_reviews([guardada], [repetida]) == [guardada]


def test_latest_date():
    assert latest_date([]) is None
    assert latest_date([["a", datetime(2021, 3, 1), 5], ["b", datetime(2021, 5, 1), 1]]) == datetime(2021, 5, 1)


def test_ventanas_de_la_tendencia():
    prev, recent = trend_windows(datetime(2021, 7, 1))
    assert (prev, recent) == (datetime(2021, 1, 1), datetime(2021, 4, 1))
    assert pre_window_start(datetime(2021, 7, 1)) == datetime(2021, 1, 1)


def test_signo_del_sentimiento():
    assert [sentiment_sign(s) for s in (1, 2, 3, 4, 5)] == [-1, -1, 0, 1, 1]


# --- decisión y documento de alerta -----------------------------------------------------------------------


def test_acciones_segun_umbral_y_estado_previo():
    activa = {"active": True}
    inactiva = {"active": False}
    assert alert_action(0.8, 0.65, None) == "raise"
    assert alert_action(0.8, 0.65, inactiva) == "raise"
    assert alert_action(0.8, 0.65, activa) == "keep"
    assert alert_action(0.3, 0.65, activa) == "clear"
    assert alert_action(0.3, 0.65, None) is None
    assert alert_action(0.3, 0.65, inactiva) is None


def test_el_umbral_es_inclusivo():
    assert alert_action(0.65, 0.65, None) == "raise"


def test_documento_de_alerta_con_geometria_probabilidad_y_fecha():
    pre = pre_aggregates([(T - timedelta(days=30), 3)])
    pre["risk_at_cutoff"] = 0.4
    t = datetime(2021, 4, 5)
    doc = build_alert("raise", pre, {"n_reviews": 10.0}, 0.8, 0.65, t, None, datetime(2026, 1, 1), model_version="v1")
    assert doc["_id"] == doc["business_id"] == "b1"
    assert doc["geometry"] == {"type": "Point", "coordinates": [-75.16, 39.95]}
    assert doc["probability"] == 0.8 and doc["threshold"] == 0.65
    assert doc["active"] is True
    assert doc["alert_date"] == t and doc["first_alert_date"] == t
    assert doc["risk_at_cutoff"] == 0.4 and doc["n_updates"] == 1 and doc["model_version"] == "v1"
    assert "cleared_date" not in doc


def test_una_alerta_que_continua_conserva_su_primera_fecha():
    pre = pre_aggregates([(T - timedelta(days=30), 3)])
    first = datetime(2021, 2, 1)
    existing = {"active": True, "first_alert_date": first, "n_updates": 2}
    doc = build_alert("keep", pre, {}, 0.9, 0.65, datetime(2021, 3, 1), existing, datetime(2026, 1, 1))
    assert doc["first_alert_date"] == first and doc["n_updates"] == 3 and doc["active"] is True


def test_una_alerta_que_baja_del_umbral_se_desactiva_con_su_fecha():
    pre = pre_aggregates([(T - timedelta(days=30), 3)])
    existing = {"active": True, "first_alert_date": datetime(2021, 2, 1), "n_updates": 1}
    t = datetime(2021, 6, 1)
    doc = build_alert("clear", pre, {}, 0.2, 0.65, t, existing, datetime(2026, 1, 1))
    assert doc["active"] is False and doc["cleared_date"] == t and doc["probability"] == 0.2


# --- avance del consumidor --------------------------------------------------------------------------------


def test_siguiente_offset_es_el_maximo_visto_mas_uno_por_particion():
    assert next_offsets([(0, 10), (0, 12), (1, 5)]) == {"0": 13, "1": 6}


def test_el_avance_nunca_retrocede():
    assert next_offsets([(0, 3)], previous={"0": 100, "2": 7}) == {"0": 100, "2": 7}
    assert next_offsets([(0, 150)], previous={"0": 100}) == {"0": 151}


def test_reprocesar_el_mismo_lote_no_cuenta_como_una_actualizacion_nueva():
    pre = pre_aggregates([(T - timedelta(days=30), 3)])
    t = datetime(2021, 3, 1)
    first = build_alert("raise", pre, {}, 0.8, 0.65, t, None, datetime(2026, 1, 1))
    again = build_alert("keep", pre, {}, 0.8, 0.65, t, first, datetime(2026, 1, 2))
    assert again["n_updates"] == first["n_updates"] == 1
    assert again["first_alert_date"] == first["first_alert_date"]


def test_una_reseña_nueva_o_otra_probabilidad_si_cuenta_como_actualizacion():
    pre = pre_aggregates([(T - timedelta(days=30), 3)])
    first = build_alert("raise", pre, {}, 0.8, 0.65, datetime(2021, 3, 1), None, datetime(2026, 1, 1))
    later = build_alert("keep", pre, {}, 0.9, 0.65, datetime(2021, 3, 9), first, datetime(2026, 1, 2))
    assert later["n_updates"] == 2
