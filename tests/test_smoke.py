"""Prueba de humo del flujo de streaming (kafka_streaming/smoke_publish.py y spark_batch/verify_smoke.py), sin Kafka ni MongoDB."""

import json
from datetime import datetime

from smoke_publish import SMOKE_TOPIC, smoke_messages
from verify_smoke import CLASSES, check_smoke_documents

T = datetime(2021, 1, 1)
RUN = "build42"


def decode(messages):
    return [(key.decode("utf-8"), json.loads(value.decode("utf-8"))) for key, value in messages]


def classified(value, sentiment=None, probabilities=None):
    """El documento que escribe streaming_inference para una reseña de la prueba de humo."""
    sentiment = (
        sentiment
        or {5.0: "positivo", 4.0: "positivo", 3.0: "neutral", 2.0: "negativo", 1.0: "negativo"}[value["stars"]]
    )
    default = {c: (0.9 if c == sentiment else 0.05) for c in CLASSES}
    return {
        "_id": value["review_id"],
        "sentiment": sentiment,
        "probabilities": probabilities or default,
        "date": datetime.fromisoformat(value["date"]),
        "processed_at": datetime(2026, 11, 19),
        "correct": True,
    }


# --- los mensajes -----------------------------------------------------------------------------------------


def test_son_100_reseñas_unicas_con_el_run_id():
    messages = decode(smoke_messages(RUN, 100))
    ids = [value["review_id"] for _, value in messages]
    assert len(ids) == len(set(ids)) == 100
    assert ids[0] == "smoke-build42-000" and ids[-1] == "smoke-build42-099"


def test_la_clave_es_el_business_id_y_el_json_tiene_los_campos_del_productor():
    for key, value in decode(smoke_messages(RUN, 10)):
        assert key == value["business_id"]
        assert set(value) == {"review_id", "business_id", "user_id", "stars", "text", "date"}
        assert isinstance(value["stars"], float) and value["text"]


def test_las_fechas_son_posteriores_a_t_y_tienen_el_formato_del_productor():
    for _, value in decode(smoke_messages(RUN, 100)):
        assert datetime.strptime(value["date"], "%Y-%m-%d %H:%M:%S") > T


def test_el_reparto_es_40_positivas_40_negativas_y_20_neutrales():
    stars = [value["stars"] for _, value in decode(smoke_messages(RUN, 100))]
    assert sum(s >= 4 for s in stars) == 40 and sum(s <= 2 for s in stars) == 40 and sum(s == 3 for s in stars) == 20


def test_es_determinista_y_otro_run_cambia_los_ids():
    assert smoke_messages(RUN, 20) == smoke_messages(RUN, 20)
    ids_a = {v["review_id"] for _, v in decode(smoke_messages("a", 20))}
    ids_b = {v["review_id"] for _, v in decode(smoke_messages("b", 20))}
    assert not ids_a & ids_b


def test_el_topic_es_aparte_del_real():
    assert SMOKE_TOPIC == "reviews-smoke"
    assert SMOKE_TOPIC != "reviews"


# --- la verificación en MongoDB ---------------------------------------------------------------------------


def good_docs(n=100):
    return [classified(value) for _, value in decode(smoke_messages(RUN, n))]


def test_las_100_clasificadas_pasan():
    problems, stats = check_smoke_documents(good_docs(), RUN, 100)
    assert problems == [] and stats["classified"] == 100 and stats["accuracy"] == 1.0


def test_sin_documentos_falla_con_el_conteo():
    problems, _ = check_smoke_documents([], RUN, 100)
    assert "hay 0 reseñas clasificadas y se esperaban 100" in problems[0]


def test_faltan_reseñas():
    problems, _ = check_smoke_documents(good_docs()[:95], RUN, 100)
    assert any("hay 95" in p for p in problems) and any("faltan 5" in p for p in problems)


def test_las_de_otra_corrida_no_cuentan():
    otros = [classified(value) for _, value in decode(smoke_messages("otro", 100))]
    problems, stats = check_smoke_documents(otros, RUN, 100)
    assert stats["classified"] == 0 and problems


def test_clase_invalida():
    docs = good_docs()
    docs[3]["sentiment"] = "enojado"
    assert any("clase inválida" in p for p in check_smoke_documents(docs, RUN, 100)[0])


def test_probabilidades_que_no_suman_uno():
    docs = good_docs()
    docs[0]["probabilities"] = {"negativo": 0.1, "neutral": 0.1, "positivo": 0.1}
    assert any("no suman 1" in p for p in check_smoke_documents(docs, RUN, 100)[0])


def test_la_clase_debe_ser_la_de_mayor_probabilidad():
    docs = good_docs()
    docs[1]["probabilities"] = {"negativo": 0.8, "neutral": 0.1, "positivo": 0.1}  # pero sentiment = positivo
    assert any("mayor probabilidad" in p for p in check_smoke_documents(docs, RUN, 100)[0])


def test_sin_fecha_o_sin_marca_de_procesamiento():
    docs = good_docs()
    docs[0]["date"] = None
    docs[1]["processed_at"] = None
    problem = check_smoke_documents(docs, RUN, 100)[0][0]
    assert problem.startswith("2 reseñas mal clasificadas")


def test_un_modelo_que_no_acierta_no_pasa():
    docs = good_docs()
    for d in docs[:50]:
        d["correct"] = False
    problems, stats = check_smoke_documents(docs, RUN, 100)
    assert stats["accuracy"] == 0.5 and any("solo coincide" in p for p in problems)
