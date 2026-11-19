import json
from datetime import datetime

import pytest

import lifemap_common
import producer
from producer import build_message, date_query, parse_date, wall_offset

T = datetime(2021, 1, 1)


def test_parse_date_texto_y_datetime():
    assert parse_date("2021-03-05 14:30:00") == datetime(2021, 3, 5, 14, 30)
    assert parse_date("2021-03-05") == datetime(2021, 3, 5)
    assert parse_date("2021-03-05T14:30:00.123Z") == datetime(2021, 3, 5, 14, 30)
    assert parse_date(datetime(2021, 3, 5, 14, 30)) == datetime(2021, 3, 5, 14, 30)


def test_parse_date_invalida():
    with pytest.raises(ValueError):
        parse_date("ayer")


def test_reloj_un_mes_cada_diez_segundos():
    # 30 días simulados = 10 s reales a la velocidad por defecto
    assert wall_offset(datetime(2021, 1, 31), T, 30, 10) == pytest.approx(10.0)
    assert wall_offset(datetime(2021, 1, 16), T, 30, 10) == pytest.approx(5.0)


def test_reloj_en_t_y_antes_de_t_es_cero():
    assert wall_offset(T, T, 30, 10) == 0.0
    assert wall_offset(datetime(2020, 12, 1), T, 30, 10) == 0.0


def test_reloj_sin_pausas():
    assert wall_offset(datetime(2021, 6, 1), T, 30, 0) == 0.0


def test_reloj_velocidad_invalida():
    with pytest.raises(ValueError):
        wall_offset(datetime(2021, 6, 1), T, 0, 10)


def test_mensaje_con_clave_business_id():
    doc = {"_id": "x", "review_id": "r1", "business_id": "b1", "user_id": "u1",
           "stars": 4, "text": "Great tacos", "date": datetime(2021, 2, 3, 4, 5, 6)}
    clave, valor = build_message(doc)
    assert clave == b"b1"
    mensaje = json.loads(valor)
    assert mensaje == {"review_id": "r1", "business_id": "b1", "user_id": "u1",
                       "stars": 4.0, "text": "Great tacos", "date": "2021-02-03 04:05:06"}


def test_mensaje_con_fecha_texto():
    doc = {"review_id": "r1", "business_id": "b1", "user_id": "u1",
           "stars": 1.0, "text": "Mala", "date": "2021-02-03 04:05:06"}
    assert json.loads(build_message(doc)[1])["date"] == "2021-02-03 04:05:06"


def test_consulta_desde_t_con_fechas_date():
    assert date_query(T) == {"date": {"$gte": T}}
    fin = datetime(2021, 7, 1)
    assert date_query(T, fin) == {"date": {"$gte": T, "$lt": fin}}


def test_consulta_desde_t_con_fechas_texto():
    # El texto "YYYY-MM-DD HH:MM:SS" se ordena igual que la fecha
    assert date_query(T, as_string=True) == {"date": {"$gte": "2021-01-01 00:00:00"}}


def test_fecha_de_corte_unica():
    # El productor usa la misma constante que el entrenamiento y el streaming (lifemap_common)
    assert producer.CUTOFF_DATE is lifemap_common.CUTOFF_DATE
    assert parse_date(lifemap_common.CUTOFF_DATE) == datetime(2021, 1, 1)
