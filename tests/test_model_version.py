"""Versión de los modelos y su registro (spark_batch/model_version.py, api_flask/sentiment.py), sin Spark ni MongoDB."""

import json

import pytest

from model_version import MODELS, model_checksum, read_model_version, registry_entry, verify_registered
from sentiment import read_model_version as api_read_model_version
from verify_model_version import compare_api_version


def make_model(root, uid="PipelineModel_abc123", timestamp=1795111713224, weights=b"\x00\x01\x02", metadata_extra=None):
    """Carpeta con la estructura de un PipelineModel guardado por Spark."""
    (root / "metadata").mkdir(parents=True)
    metadata = {
        "class": "org.apache.spark.ml.PipelineModel",
        "timestamp": timestamp,
        "uid": uid,
        **(metadata_extra or {}),
    }
    (root / "metadata" / "part-00000").write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    (root / "metadata" / "_SUCCESS").write_text("")
    (root / "metadata" / ".part-00000.crc").write_bytes(b"crc")
    (root / "stages" / "0_VectorAssembler").mkdir(parents=True)
    (root / "stages" / "0_VectorAssembler" / "data.bin").write_bytes(weights)
    return root


# --- versión ----------------------------------------------------------------------------------------------


def test_la_version_es_uid_y_timestamp(tmp_path):
    model = make_model(tmp_path / "m")
    assert read_model_version(str(model)) == "PipelineModel_abc123@1795111713224"


def test_sin_modelo_no_hay_version(tmp_path):
    assert read_model_version(str(tmp_path / "no_existe")) is None
    (tmp_path / "vacio" / "metadata").mkdir(parents=True)
    assert read_model_version(str(tmp_path / "vacio")) is None


def test_dos_entrenamientos_tienen_versiones_distintas(tmp_path):
    a = make_model(tmp_path / "a", uid="PipelineModel_aaa", timestamp=1)
    b = make_model(tmp_path / "b", uid="PipelineModel_bbb", timestamp=2)
    assert read_model_version(str(a)) != read_model_version(str(b))


def test_la_api_y_spark_calculan_la_misma_version(tmp_path):
    model = make_model(tmp_path / "m")
    assert api_read_model_version(str(model)) == read_model_version(str(model))
    assert api_read_model_version(str(tmp_path / "no_existe")) is None


# --- suma de verificación ---------------------------------------------------------------------------------


def test_la_suma_de_verificacion_es_estable(tmp_path):
    model = make_model(tmp_path / "m")
    assert model_checksum(str(model)) == model_checksum(str(model))


def test_cambiar_un_peso_cambia_la_suma(tmp_path):
    a = make_model(tmp_path / "a", weights=b"\x00\x01\x02")
    b = make_model(tmp_path / "b", weights=b"\x00\x01\x03")
    assert model_checksum(str(a)) != model_checksum(str(b))


def test_el_mismo_modelo_en_otra_carpeta_da_la_misma_suma(tmp_path):
    assert model_checksum(str(make_model(tmp_path / "a"))) == model_checksum(str(make_model(tmp_path / "b")))


def test_success_y_crc_no_cuentan(tmp_path):
    model = make_model(tmp_path / "m")
    before = model_checksum(str(model))
    (model / "_SUCCESS").write_text("x")
    (model / "stages" / "0_VectorAssembler" / ".data.bin.crc").write_bytes(b"otro crc")
    assert model_checksum(str(model)) == before


def test_renombrar_un_archivo_cambia_la_suma(tmp_path):
    model = make_model(tmp_path / "m")
    before = model_checksum(str(model))
    (model / "stages" / "0_VectorAssembler" / "data.bin").rename(model / "stages" / "0_VectorAssembler" / "otro.bin")
    assert model_checksum(str(model)) != before


# --- registro y verificación ------------------------------------------------------------------------------


def test_entrada_del_registro(tmp_path):
    model = make_model(tmp_path / "m")
    entry = registry_entry("risk_best", str(model), metrics_id="risk", trained_at="2026-11-19")
    assert entry["_id"] == entry["name"] == "risk_best"
    assert entry["version"] == "PipelineModel_abc123@1795111713224"
    assert entry["checksum"] == model_checksum(str(model))
    assert entry["metrics_id"] == "risk" and entry["registered_at"] is not None


def test_sin_modelo_no_hay_entrada(tmp_path):
    assert registry_entry("x", str(tmp_path / "no_existe")) is None


def test_el_modelo_en_disco_es_el_registrado(tmp_path):
    model = make_model(tmp_path / "m")
    entry = registry_entry("m", str(model))
    assert verify_registered(entry, read_model_version(str(model)), model_checksum(str(model))) == []


def test_un_modelo_sin_registrar_falla():
    assert verify_registered(None, "v", "c") == ["el modelo no está registrado en model_registry"]


def test_un_modelo_reentrenado_sin_registrar_falla(tmp_path):
    viejo = make_model(tmp_path / "viejo", uid="PipelineModel_old", timestamp=1)
    entry = registry_entry("m", str(viejo))
    nuevo = make_model(tmp_path / "nuevo", uid="PipelineModel_new", timestamp=2, weights=b"\x09")
    problems = verify_registered(entry, read_model_version(str(nuevo)), model_checksum(str(nuevo)))
    assert any("versión registrada" in p for p in problems) and any("suma de verificación" in p for p in problems)


def test_un_modelo_alterado_con_la_misma_version_falla(tmp_path):
    model = make_model(tmp_path / "m")
    entry = registry_entry("m", str(model))
    (model / "stages" / "0_VectorAssembler" / "data.bin").write_bytes(b"alterado")
    problems = verify_registered(entry, read_model_version(str(model)), model_checksum(str(model)))
    assert problems == [
        "la suma de verificación del disco no coincide con la registrada: el modelo cambió o está alterado"
    ]


def test_sin_modelo_en_disco_falla():
    assert verify_registered({"version": "v", "checksum": "c"}, None, None) == ["no hay modelo en disco"]


def test_los_modelos_registrados_son_los_que_guardan_los_jobs():
    assert {"sentiment_best", "risk_best"} <= set(MODELS)
    assert MODELS["risk_best"] == ("risk_best", "risk")


# --- lo que informa la API --------------------------------------------------------------------------------


def test_la_api_responde_con_el_modelo_registrado():
    assert compare_api_version("v1", "v1", "v1") == []


def test_la_api_con_otro_modelo_falla():
    problems = compare_api_version("v2", "v1", "v1")
    assert len(problems) == 2 and "/predict" in problems[0] and "/health" in problems[1]


def test_la_api_que_no_informa_version_falla():
    problems = compare_api_version("v1", None, None)
    assert any("no informó" in p for p in problems)


@pytest.mark.parametrize("health", [None, "otra"])
def test_health_con_otra_version_o_sin_ella_falla(health):
    assert any("/health" in p for p in compare_api_version("v1", "v1", health))
