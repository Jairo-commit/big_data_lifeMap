"""Entrega 2, punto 5: curvas de supervivencia de Kaplan-Meier con censura y entrada tardía.

Lógica pura (sin Spark ni MongoDB): se prueba con pytest (tests/test_survival.py) y la usa `survival_km.py`.

Cómo se modela un negocio (la guía parte de las reseñas, no hay fechas de apertura ni de cierre):

- Tiempo = días desde la primera reseña hasta la última (la misma "vida" que `days_business`).
- Evento = cierre observado (`is_open = 0`). Un negocio abierto está **censurado**: solo se sabe que seguía
  vivo en la fecha de corte del dataset.
- **Entrada tardía** (truncamiento por la izquierda): la ventana de observación empieza en `window_start`
  (W0). Un negocio cuya primera reseña es anterior a W0 "ya venía funcionando": solo se le observa desde W0,
  así que entra al conjunto en riesgo con la edad que ya tenía en ese momento (`W0 - primera reseña`). Si se
  le contara desde la edad 0 se inflaría la supervivencia, porque los negocios que murieron antes de W0 no
  están en los datos. Los negocios que terminan antes de W0 no se observaron y se excluyen.

En riesgo en el instante t: los negocios con `entrada < t <= salida`.
"""

import math
from bisect import bisect_left
from collections import Counter
from datetime import datetime

from geo_windows import quantile

Z_95 = 1.959963984540054
MIN_BUSINESSES = 100
MIN_EVENTS = 20
DAYS_PER_YEAR = 365.25


def primary_category(categories):
    """Categoría principal de un negocio de Yelp: la primera de la lista `categories` separada por comas."""
    first = (categories or "").split(",")[0].strip()
    return first or "Sin categoría"


def business_record(first_review, last_review, is_open, window_start):
    """(entrada, tiempo, evento) de un negocio en días, o None si no se observó dentro de la ventana.

    `first_review`, `last_review` y `window_start` son datetime. La vida mínima es 1 día, como en
    `days_business`.
    """
    duration = max((last_review - first_review).days, 1)
    entry = max((window_start - first_review).days, 0)
    if duration <= entry:
        return None  # dejó de tener actividad antes de que empezara la ventana
    return entry, duration, 0 if is_open else 1


def kaplan_meier(records, z=Z_95):
    """Estimador de Kaplan-Meier con censura y entrada tardía.

    `records`: iterable de (entrada, tiempo, evento) en días, evento 1 = cierre, 0 = censurado. Los registros con
    `tiempo <= entrada` no llegan a estar en riesgo y se ignoran.

    Devuelve un dict con `n`, `n_events`, `n_censored`, `n_late_entry`, `median` (None si la curva no baja
    de 0,5) y `curve`: una fila por instante en que hubo cierres, con `t`, `n_risk`, `n_events`,
    `n_censored` (los censurados justo en t), `survival` y su intervalo de confianza del 95 %
    (Greenwood exponencial, el mismo método de lifelines).
    """
    entries, times = [], []
    events_at, censored_at = Counter(), Counter()
    late = 0
    for entry, time, event in records:
        if time <= entry:
            continue
        entries.append(entry)
        times.append(time)
        late += entry > 0
        (events_at if event else censored_at)[time] += 1
    entries.sort()
    times.sort()

    survival, greenwood = 1.0, 0.0
    curve, median = [], None
    for t in sorted(events_at):
        n_risk = bisect_left(entries, t) - bisect_left(times, t)  # entrada < t <= salida
        d = events_at[t]
        survival *= 1 - d / n_risk
        greenwood += d / (n_risk * (n_risk - d)) if n_risk > d else math.inf
        lower, upper = _confidence_interval(survival, greenwood, z)
        curve.append(
            {
                "t": t,
                "n_risk": n_risk,
                "n_events": d,
                "n_censored": censored_at.get(t, 0),
                "survival": survival,
                "ci_low": lower,
                "ci_high": upper,
            }
        )
        if median is None and survival <= 0.5:
            median = t

    n_events = sum(events_at.values())
    return {
        "n": len(times),
        "n_events": n_events,
        "n_censored": len(times) - n_events,
        "n_late_entry": late,
        "median": median,
        "curve": curve,
    }


def _confidence_interval(survival, greenwood, z):
    """IC log-log: S^exp(±z·σ), con σ = sqrt(Greenwood) / |ln S|. Si S llega a 0 el intervalo es [0, 0]."""
    if survival <= 0 or math.isinf(greenwood):
        return 0.0, 0.0
    sigma = math.sqrt(greenwood) / abs(math.log(survival)) if survival < 1 else 0.0
    return survival ** math.exp(z * sigma), survival ** math.exp(-z * sigma)


def survival_at(curve, t):
    """S(t): la curva es una función escalonada; antes del primer cierre vale 1."""
    value = 1.0
    for point in curve:
        if point["t"] > t:
            break
        value = point["survival"]
    return value


def meets_min(n, n_events, min_businesses=MIN_BUSINESSES, min_events=MIN_EVENTS):
    """Un grupo pequeño no permite conclusiones: hacen falta negocios y cierres suficientes."""
    return n >= min_businesses and n_events >= min_events


def years(days):
    return None if days is None else days / DAYS_PER_YEAR


def bounding_polygon(coords, low=0.01, high=0.99, pad=0.002):
    """Polígono GeoJSON (rectángulo) que encierra la zona de un grupo de negocios.

    `coords` son pares (lon, lat). Se recortan los percentiles `low` y `high` de cada eje para que unos pocos
    negocios lejanos (errores de coordenadas, otras ciudades) no estiren la zona, y se añade `pad` grados.
    El anillo sale cerrado y en sentido antihorario, como pide $geoWithin.
    """
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    west, east = quantile(lons, low) - pad, quantile(lons, high) + pad
    south, north = quantile(lats, low) - pad, quantile(lats, high) + pad
    return {
        "type": "Polygon",
        "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
    }


def window_start_datetime(text):
    return datetime.strptime(text, "%Y-%m-%d")
