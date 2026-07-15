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


def test_macos_arm64_workflow_runs_the_runtime_profiles() -> None:
    workflow = Path(".github/workflows/m0-rapidocr-macos-arm64.yml").read_text(encoding="utf-8")
    assert "runs-on: macos-14" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "platform.machine().lower()" in workflow
    assert "prototypes/rapidocr_multilingual/requirements.lock" in workflow
    assert "python -m pytest tests/prototypes/rapidocr_multilingual -q" in workflow
    assert '("zh-Hans", "ru", "ko", "th", "ar", "hi")' in workflow
    assert "actions/upload-artifact@v4" in workflow
