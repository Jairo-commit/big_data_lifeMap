"""Entrega 2, punto 6: lógica pura del modelo de riesgo de cierre (sin Spark ni MongoDB).

Es el patrón de KafkaMed (variables por entidad + clasificador de riesgo + umbral para alertar) aplicado a
negocios. La usa `risk_model.py` y se prueba con pytest (tests/test_risk_logic.py).

Todo se define respecto a la fecha de corte T (CUTOFF_DATE):

- **Población**: negocios que ya existían en T (tienen reseñas anteriores a T) y siguen con actividad después
  de T (su última reseña es >= T). Los que no tuvieron actividad desde T se excluyen: no se sabe nada de ellos
  que sirva para pronosticar.
- **Etiqueta**: 1 si el negocio está cerrado (`is_open = 0`) y su última reseña cae entre T y T + 12 meses;
  0 si sigue con actividad después de ese plazo o sigue abierto.
- **Variables**: se calculan solo con reseñas anteriores a T, para no filtrar el futuro al modelo.
"""

from calendar import monthrange

HORIZON_MONTHS = 12
TREND_HALF_MONTHS = 3  # la tendencia de los últimos 6 meses compara sus dos mitades de 3 meses
MIN_TREND_REVIEWS = 5  # reseñas mínimas en cada mitad para que el % negativo no sea ruido
COMPETITOR_RADIUS_M = 500

# Variables del modelo, en el orden del VectorAssembler
FEATURES = [
    "mean_sentiment",
    "neg_trend_6m",
    "stars_mean",
    "n_reviews",
    "age_days",
    "competitors_500m",
]


def add_months(dt, months):
    """dt + months meses (puede ser negativo); si el día no existe en el mes destino se usa el último."""
    index = dt.year * 12 + (dt.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return dt.replace(year=year, month=month, day=min(dt.day, monthrange(year, month)[1]))


def in_population(first_review, last_review, cutoff):
    """Existía en T (reseñas antes de T) y tuvo actividad desde T."""
    return first_review < cutoff <= last_review


def risk_label(is_open, last_review, cutoff, horizon_months=HORIZON_MONTHS):
    """Etiqueta de riesgo: 1 cierra dentro de [T, T + horizonte], 0 si no; None si está fuera de la población.

    `is_open` es 1/0 (o booleano) tal como viene de Yelp. Un negocio cerrado cuya última reseña es posterior al
    horizonte cuenta como 0: siguió con actividad más allá de los 12 meses.
    """
    if last_review < cutoff:
        return None
    if not is_open and last_review <= add_months(cutoff, horizon_months):
        return 1
    return 0


def mean_sentiment(n_positive, n_negative, n_reviews):
    """Sentimiento medio en [-1, 1]: positiva +1, neutral 0 y negativa -1 (la regla de las etiquetas por estrellas)."""
    return (n_positive - n_negative) / n_reviews if n_reviews else None


def negative_trend(neg_recent, n_recent, neg_prev, n_prev, min_reviews=MIN_TREND_REVIEWS):
    """Tendencia del % de reseñas negativas en los últimos 6 meses, en puntos porcentuales.

    % negativo de los 3 meses más recientes menos el de los 3 anteriores: positivo = el negocio se está
    deteriorando. Si alguna de las dos mitades tiene menos de `min_reviews` reseñas la tendencia no es
    fiable y se devuelve 0.0 (sin tendencia) en lugar de un número que sería puro ruido.
    """
    if n_recent < min_reviews or n_prev < min_reviews:
        return 0.0
    return neg_recent / n_recent * 100 - neg_prev / n_prev * 100


def competitors_pipeline(lon, lat, category, business_id, radius_m=COMPETITOR_RADIUS_M):
    """Agregación de MongoDB con $geoNear: cuántos otros negocios de la misma categoría hay a <= radius_m.

    Se ejecuta sobre `risk_features` (los negocios de la población, ya activos en T), así que los competidores
    son negocios que existían y operaban en T. Se excluye al propio negocio.
    """
    return [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [lon, lat]},
                "distanceField": "distance_m",
                "maxDistance": radius_m,
                "spherical": True,
                "query": {"primary_category": category, "business_id": {"$ne": business_id}},
            }
        },
        {"$count": "competitors"},
    ]


# ---------------------------------------------------------------------------
# Umbral y métricas en el umbral
# ---------------------------------------------------------------------------


def confusion_at(scores, labels, threshold):
    """Matriz de confusión prediciendo 1 cuando score >= threshold."""
    tp = fp = fn = tn = 0
    for score, label in zip(scores, labels):
        if score >= threshold:
            if label:
                tp += 1
            else:
                fp += 1
        elif label:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def metrics_at_threshold(scores, labels, threshold):
    """Precision, recall, F1 y tasa de alertas con las predicciones en un umbral."""
    tp, fp, fn, tn = confusion_at(scores, labels, threshold)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total = tp + fp + fn + tn
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "alert_rate": (tp + fp) / total if total else 0.0,
    }


def choose_threshold(scores, labels):
    """Umbral que maximiza el F1 sobre un conjunto de validación (score = probabilidad de cierre).

    Con clases muy desbalanceadas 0,5 casi nunca alerta; el F1 equilibra precision y recall. Se recorre cada
    puntuación distinta como candidato (predecir 1 cuando score >= umbral) en una sola pasada ordenada.
    """
    pairs = sorted(zip(scores, labels), key=lambda p: -p[0])
    positives = sum(1 for _, label in pairs if label)
    if not pairs or positives == 0:
        return None
    best_threshold, best_f1 = None, -1.0
    tp = fp = 0
    index = 0
    while index < len(pairs):
        score = pairs[index][0]
        while index < len(pairs) and pairs[index][0] == score:  # los empates entran juntos
            tp += 1 if pairs[index][1] else 0
            fp += 0 if pairs[index][1] else 1
            index += 1
        precision, recall = tp / (tp + fp), tp / positives
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if f1 > best_f1:
            best_threshold, best_f1 = score, f1
    return best_threshold


def prevalence(labels):
    """Proporción de positivos: es el AUC-PR de un clasificador sin información (la base de comparación)."""
    return sum(1 for label in labels if label) / len(labels) if labels else None
