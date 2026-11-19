"""Entrega 2, punto 4: lógica pura de las ventanas geoespaciales y la detección de hotspots.

No usa Spark ni MongoDB: se prueba con pytest (tests/test_geo_windows.py). Los jobs que la usan son
`calibrate_hotspots.py` (fija el umbral con el histórico anterior a T) y `streaming_windows.py` (ventanas
en streaming sobre el topic de Kafka).

Ventana: 30 días, alineadas con la fecha de corte T (la primera ventana empieza exactamente en T), por
celda de geohash y sobre el tiempo del evento (el campo `date` de la reseña, no el de ingesta).

Hotspot: una celda es hotspot en una ventana cuando su porcentaje de reseñas negativas sube frente a la
ventana anterior de la misma celda por encima de un umbral, siempre que ambas ventanas tengan reseñas
suficientes para que el porcentaje no sea ruido. El umbral no se elige a ojo: `calibrate_hotspots.py` lo
toma del histórico (percentil 95 de las variaciones mes a mes), ver `calibrate_threshold`.
"""

import math
from datetime import datetime, timedelta, timezone

from lifemap_common import geohash_centroid, geohash_polygon

EPOCH = datetime(1970, 1, 1)
DEFAULT_WINDOW_DAYS = 30
DEFAULT_WATERMARK_DAYS = 7
# Con n reseñas el error estándar de un porcentaje es sqrt(p(1-p)/n): con 20 reseñas llega a ±11 puntos
# (ver standard_error_pp), con menos un "salto" de 10 puntos no se distingue del azar.
DEFAULT_MIN_REVIEWS = 20
DEFAULT_QUANTILE = 0.95
# Solo se usa si todavía no se ha ejecutado calibrate_hotspots.py (no existe hotspot_config)
FALLBACK_THRESHOLD_PP = 20.0


# ---------------------------------------------------------------------------
# Fechas y ventanas
# ---------------------------------------------------------------------------


def parse_day(text):
    """'2021-01-01' -> datetime (medianoche, sin zona: todo el sistema trabaja en UTC)."""
    return datetime.strptime(text, "%Y-%m-%d")


def window_offset_days(cutoff, window_days=DEFAULT_WINDOW_DAYS):
    """Desplazamiento (`startTime` de la ventana de Spark) para que las ventanas empiecen en T.

    Spark alinea las ventanas respecto al 1970-01-01. Con ventanas de `window_days` días, empezar en T
    equivale a desplazar `(días desde 1970 hasta T) mod window_days` días. Con T = 2021-01-01 y 30 días
    son 28 días.
    """
    return (parse_day(cutoff) - EPOCH).days % window_days


def from_epoch_seconds(seconds):
    """Segundos desde 1970 -> datetime UTC sin zona (lo que guarda pymongo como fecha)."""
    return EPOCH + timedelta(seconds=int(seconds))


def window_id(geohash, window_start):
    """Identificador estable de una ventana de una celda (clave del upsert: reprocesar no duplica)."""
    return f"{geohash}|{window_start:%Y-%m-%d}"


def previous_window_start(window_start, window_days=DEFAULT_WINDOW_DAYS):
    return window_start - timedelta(days=window_days)


# ---------------------------------------------------------------------------
# Porcentajes y regla de hotspot
# ---------------------------------------------------------------------------


def percent(part, total):
    """Porcentaje (0-100); None si no hay reseñas, porque no está definido."""
    return part / total * 100 if total else None


def standard_error_pp(pct, n):
    """Error estándar de un porcentaje con n reseñas, en puntos porcentuales: sqrt(p(1-p)/n)."""
    if not n:
        return None
    p = pct / 100
    return math.sqrt(p * (1 - p) / n) * 100


def hotspot_decision(n_reviews, pct_negative, previous, threshold_pp, min_reviews=DEFAULT_MIN_REVIEWS):
    """Decide si una ventana es hotspot frente a la ventana anterior de la misma celda.

    `previous` es None o un dict con `n_reviews` y `pct_negative` de la ventana anterior. Devuelve los
    campos que se guardan junto a la ventana, con `hotspot_reason` para poder explicar cada decisión:
    sin_ventana_previa, sin_porcentaje, pocas_resenas, pocas_resenas_previa, bajo_umbral o hotspot.
    """
    info = {"prev_n_reviews": None, "prev_pct_negative": None, "delta_pp": None, "is_hotspot": False}
    if previous is None:
        info["hotspot_reason"] = "sin_ventana_previa"
        return info

    info["prev_n_reviews"] = previous.get("n_reviews")
    info["prev_pct_negative"] = previous.get("pct_negative")
    if pct_negative is None or info["prev_pct_negative"] is None:
        info["hotspot_reason"] = "sin_porcentaje"
        return info

    info["delta_pp"] = pct_negative - info["prev_pct_negative"]
    if n_reviews < min_reviews:
        info["hotspot_reason"] = "pocas_resenas"
    elif info["prev_n_reviews"] < min_reviews:
        info["hotspot_reason"] = "pocas_resenas_previa"
    elif info["delta_pp"] >= threshold_pp:
        info["is_hotspot"] = True
        info["hotspot_reason"] = "hotspot"
    else:
        info["hotspot_reason"] = "bajo_umbral"
    return info


def build_window_docs(
    rows,
    stored_previous,
    threshold_pp,
    min_reviews=DEFAULT_MIN_REVIEWS,
    window_days=DEFAULT_WINDOW_DAYS,
    processed_at=None,
):
    """Documentos de `geohash_windows` a partir de las ventanas cerradas de un micro-lote.

    `rows`: dicts con geohash, window_start y window_end (segundos desde 1970), n_reviews, n_negative,
    n_neutral, n_positive y n_negative_stars. `stored_previous`: ventanas ya guardadas en MongoDB por
    `_id`; la ventana anterior se busca primero en el propio lote y luego ahí. Cada documento lleva la
    geometría de su celda para poder consultarlo con $geoWithin / $geoIntersects.
    """
    started = [(r, from_epoch_seconds(r["window_start"])) for r in rows]
    in_batch = {}
    for row, start in started:
        in_batch[window_id(row["geohash"], start)] = {
            "n_reviews": row["n_reviews"],
            "pct_negative": percent(row["n_negative"], row["n_reviews"]),
        }

    docs = []
    for row, start in sorted(started, key=lambda item: (item[1], item[0]["geohash"])):
        wid = window_id(row["geohash"], start)
        pct = percent(row["n_negative"], row["n_reviews"])
        previous_id = window_id(row["geohash"], previous_window_start(start, window_days))
        previous = in_batch.get(previous_id) or stored_previous.get(previous_id)

        doc = {
            "_id": wid,
            "geohash": row["geohash"],
            "window_start": start,
            "window_end": from_epoch_seconds(row["window_end"]),
            "window_days": window_days,
            "n_reviews": row["n_reviews"],
            "n_negative": row["n_negative"],
            "n_neutral": row["n_neutral"],
            "n_positive": row["n_positive"],
            "pct_negative": pct,
            "n_negative_stars": row["n_negative_stars"],
            "pct_negative_stars": percent(row["n_negative_stars"], row["n_reviews"]),
            "threshold_pp": threshold_pp,
            "min_reviews": min_reviews,
            "geometry": geohash_polygon(row["geohash"]),
            "centroid": geohash_centroid(row["geohash"]),
            "processed_at": processed_at or datetime.now(timezone.utc).replace(tzinfo=None),
        }
        doc.update(hotspot_decision(row["n_reviews"], pct, previous, threshold_pp, min_reviews))
        docs.append(doc)
    return docs


def missing_previous_ids(rows, window_days=DEFAULT_WINDOW_DAYS):
    """`_id` de las ventanas anteriores que no están en el lote y hay que leer de MongoDB."""
    present = {window_id(r["geohash"], from_epoch_seconds(r["window_start"])) for r in rows}
    wanted = {
        window_id(r["geohash"], previous_window_start(from_epoch_seconds(r["window_start"]), window_days)) for r in rows
    }
    return wanted - present


# ---------------------------------------------------------------------------
# Calibración del umbral con el histórico
# ---------------------------------------------------------------------------


def quantile(values, q):
    """Cuantil con interpolación lineal (el mismo método que numpy.quantile por defecto)."""
    if not values:
        return None
    if not 0 <= q <= 1:
        raise ValueError("q debe estar entre 0 y 1")
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize_deltas(deltas):
    """Resumen de la distribución de variaciones mes a mes del % negativo de las celdas (en puntos)."""
    n = len(deltas)
    if n == 0:
        return {"n_pairs": 0}
    mean = sum(deltas) / n
    variance = sum((d - mean) ** 2 for d in deltas) / (n - 1) if n > 1 else 0.0
    return {
        "n_pairs": n,
        "mean": mean,
        "std": math.sqrt(variance),
        "min": min(deltas),
        "max": max(deltas),
        "p50": quantile(deltas, 0.50),
        "p90": quantile(deltas, 0.90),
        "p95": quantile(deltas, 0.95),
        "p99": quantile(deltas, 0.99),
    }


def calibrate_threshold(deltas, q=DEFAULT_QUANTILE):
    """Umbral de hotspot: el cuantil q de las variaciones históricas (nunca negativo).

    Con q = 0,95 una celda es hotspot cuando su porcentaje negativo sube más de lo que sube en el 95 % de
    los casos históricos, es decir, un salto que solo ocurre 1 de cada 20 veces por azar o tendencia normal.
    """
    value = quantile(deltas, q)
    return None if value is None else max(value, 0.0)
