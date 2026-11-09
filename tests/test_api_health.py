"""Estado general de /health (api_flask/sentiment.py), sin Flask, Spark ni MongoDB."""

import pytest

from sentiment import overall_status


@pytest.mark.parametrize("model_status", ["loaded", "not_loaded", "not_trained"])
def test_ok_when_mongodb_is_healthy_and_the_model_is_fine_or_not_trained(model_status):
    assert overall_status("healthy", model_status) == "ok"


def test_degraded_when_a_trained_model_fails_to_load():
    assert overall_status("healthy", "error: No module named 'numpy'") == "degraded"


def test_degraded_when_mongodb_is_down():
    assert overall_status("unhealthy: timeout", "loaded") == "degraded"
