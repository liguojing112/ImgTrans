from __future__ import annotations

from pathlib import Path

import pytest

from prototypes.rapidocr_multilingual.model_router import (
    LANGUAGE_CODES,
    ModelRouter,
    RoutingError,
)


CONFIG = Path("prototypes/rapidocr_multilingual/model-config.json")


def test_router_covers_exactly_the_25_language_baseline() -> None:
    router = ModelRouter(CONFIG)
    coverage = router.coverage_matrix()
    assert len(LANGUAGE_CODES) == 25
    assert {item["language_code"] for item in coverage} == set(LANGUAGE_CODES)


def test_bengali_is_explicitly_unsupported_instead_of_misrouted() -> None:
    route = ModelRouter(CONFIG).route("bn")
    assert route.supported is False
    assert route.model_id is None
    assert "Bengali" in (route.reason or "")
    with pytest.raises(RoutingError):
        route.engine_params()


def test_script_families_use_distinct_recognition_profiles() -> None:
    router = ModelRouter(CONFIG)
    assert router.route("ru").model_id == "ppocrv5-cyrillic-mobile"
    assert router.route("ur").model_id == "ppocrv5-arabic-mobile"
    assert router.route("hi").model_id == "ppocrv5-devanagari-mobile"
    assert router.route("th").model_id == "ppocrv5-thai-mobile"
    assert router.route("en").model_id == "ppocrv6-multilingual-small"


def test_out_of_scope_language_is_rejected() -> None:
    with pytest.raises(RoutingError, match="outside"):
        ModelRouter(CONFIG).route("nl")

