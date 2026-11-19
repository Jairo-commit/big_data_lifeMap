"""Entrega 2, punto 7: lógica pura de las alertas de riesgo en streaming (sin Spark ni MongoDB).

La usa `streaming_alerts.py` y se prueba con pytest (tests/test_alerts_logic.py).

Cuando llega una reseña de un negocio, sus variables de riesgo se **actualizan al instante t de su última reseña**
y se vuelven a puntuar con el modelo. Las seis variables son las mismas del entrenamiento (risk_logic.FEATURES) y se
calculan solo con reseñas de fecha <= t, así que el modelo nunca ve el futuro:

- La parte anterior a T sale de `risk_features` (las variables que se calcularon a T con las reseñas < T) y, para la
  tendencia, de las reseñas < T que caen dentro de la ventana de 6 meses que termina en t.
- La parte posterior a T sale de las reseñas que llegan por Kafka, guardadas por negocio y por `review_id` (repetir un
  micro-lote no las cuenta dos veces).

Propiedad que prueban los tests: aplicar las reseñas lote a lote da las mismas variables que recalcularlas de cero.
"""

from risk_logic import MIN_TREND_REVIEWS, TREND_HALF_MONTHS, add_months, negative_trend

NEGATIVE_MAX_STARS = 2  # 1-2 estrellas: negativa
POSITIVE_MIN_STARS = 4  # 4-5 estrellas: positiva


def sentiment_sign(stars):
    """+1 positiva, -1 negativa, 0 neutral: la misma regla de las etiquetas por estrellas."""
    if stars >= POSITIVE_MIN_STARS:
        return 1
    if stars <= NEGATIVE_MAX_STARS:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Estado por negocio: las reseñas posteriores a T que han llegado
# ---------------------------------------------------------------------------


def merge_reviews(existing, incoming):
    """Une las reseñas guardadas con las que llegan, sin duplicar por review_id (idempotente) y ordenadas por fecha.

    Cada reseña es una lista [review_id, fecha (datetime), estrellas]. Si un id se repite, gana la ya guardada.
    """
    by_id = {}
    for review in list(incoming) + list(existing):  # las guardadas van al final y pisan a las repetidas
        by_id[review[0]] = review
    return sorted(by_id.values(), key=lambda r: (r[1], r[0]))


def latest_date(reviews):
    """Instante t de un negocio: la fecha de su reseña más reciente."""
    return max(r[1] for r in reviews) if reviews else None


# ---------------------------------------------------------------------------
# Variables al instante t
# ---------------------------------------------------------------------------


def trend_windows(t):
    """Inicio de la mitad reciente [t-3m, t] y de la anterior [t-6m, t-3m) de la tendencia."""
    return add_months(t, -2 * TREND_HALF_MONTHS), add_months(t, -TREND_HALF_MONTHS)


def pre_window_start(t):
    """Desde cuándo hay que traer reseñas anteriores a T para la tendencia: t - 6 meses."""
    return add_months(t, -2 * TREND_HALF_MONTHS)


def features_at(pre, post_reviews, pre_window_reviews, t, min_trend_reviews=MIN_TREND_REVIEWS):
    """Las seis variables de riesgo de un negocio al instante t, solo con reseñas de fecha <= t.

    `pre`: documento de `risk_features` (variables a T): n_reviews, stars_mean, mean_sentiment, competitors_500m y
    first_review. `post_reviews`: reseñas posteriores a T que han llegado [[id, fecha, estrellas], ...].
    `pre_window_reviews`: reseñas anteriores a T [[fecha, estrellas], ...] que caen en [t-6m, T); solo se usan para la
    tendencia (el resto de variables ya vienen agregadas en `pre`).
    """
    post = [r for r in post_reviews if r[1] <= t]
    n_pre = pre["n_reviews"]
    n = n_pre + len(post)
    stars_total = pre["stars_mean"] * n_pre + sum(r[2] for r in post)
    sentiment_total = pre["mean_sentiment"] * n_pre + sum(sentiment_sign(r[2]) for r in post)

    prev_start, recent_start = trend_windows(t)
    recent = [s for d, s in pre_window_reviews if recent_start <= d <= t] + [
        r[2] for r in post if recent_start <= r[1] <= t
    ]
    previous = [s for d, s in pre_window_reviews if prev_start <= d < recent_start] + [
        r[2] for r in post if prev_start <= r[1] < recent_start
    ]
    trend = negative_trend(
        sum(1 for s in recent if s <= NEGATIVE_MAX_STARS),
        len(recent),
        sum(1 for s in previous if s <= NEGATIVE_MAX_STARS),
        len(previous),
        min_trend_reviews,
    )
    return {
        "mean_sentiment": sentiment_total / n,
        "neg_trend_6m": trend,
        "stars_mean": stars_total / n,
        "n_reviews": float(n),
        "age_days": float((t - pre["first_review"]).days),
        "competitors_500m": float(pre["competitors_500m"]),
    }


# ---------------------------------------------------------------------------
# Decisión y documento de alerta
# ---------------------------------------------------------------------------


def alert_action(probability, threshold, existing):
    """Qué hacer con la alerta de un negocio tras puntuarlo: 'raise', 'keep' (sigue activa), 'clear' o None.

    `existing` es la alerta guardada (dict) o None. Supera el umbral cuando probability >= threshold.
    """
    above = probability >= threshold
    was_active = bool(existing and existing.get("active"))
    if above:
        return "keep" if was_active else "raise"
    return "clear" if was_active else None


def build_alert(action, pre, features, probability, threshold, t, existing, processed_at, model_version=None):
    """Documento de `alerts` (un negocio = un documento, `_id` = business_id) tras una acción 'raise', 'keep' o 'clear'.

    Guarda la geometría del negocio (Point GeoJSON), la probabilidad, la fecha del evento y las variables con las
    que se puntuó. La primera vez que se activa fija `first_alert_date`; `risk_at_cutoff` es la probabilidad a T.
    """
    existing = existing or {}
    # Releer un lote ya procesado (mismo instante y misma probabilidad) no es una actualización nueva
    is_replay = existing.get("alert_date") == t and existing.get("probability") == probability
    doc = {
        "_id": pre["business_id"],
        "business_id": pre["business_id"],
        "city": pre.get("city"),
        "primary_category": pre.get("primary_category"),
        "geometry": pre["location"],
        "probability": probability,
        "threshold": threshold,
        "active": action != "clear",
        "alert_date": t,
        "first_alert_date": existing.get("first_alert_date") or t,
        "features": features,
        "risk_at_cutoff": pre.get("risk_at_cutoff"),
        "n_updates": existing.get("n_updates", 0) + (0 if is_replay else 1),
        "processed_at": processed_at,
    }
    if action == "clear":
        doc["cleared_date"] = t
    if model_version:
        doc["model_version"] = model_version
    return doc


# ---------------------------------------------------------------------------
# Avance del consumidor (base del retraso de /health)
# ---------------------------------------------------------------------------


def next_offsets(rows, previous=None):
    """Siguiente offset por partición tras un lote: máximo offset visto + 1 (nunca retrocede)."""
    offsets = dict(previous or {})
    for partition, offset in rows:
        key = str(partition)
        offsets[key] = max(offsets.get(key, 0), offset + 1)
    return offsets
