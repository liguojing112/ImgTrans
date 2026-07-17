from __future__ import annotations

import os
import platform

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from src.domain.language import SUPPORTED_LANGUAGE_CODES
from src.platform.fonts import (
    _preferred_families,
    _select_font,
    resolve_system_font_details,
)


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    return QApplication.instance() or QApplication(["font-resolution-visual-test"])


@pytest.mark.parametrize("system", ("Windows", "Darwin"))
def test_every_supported_language_has_platform_font_preferences(system: str) -> None:
    assert len(SUPPORTED_LANGUAGE_CODES) == 25
    for language_code in SUPPORTED_LANGUAGE_CODES:
        assert _preferred_families(language_code, system)


def test_font_resolution_reports_primary_and_degraded_fallbacks() -> None:
    primary = _select_font("ar", "Windows", ("Nirmala UI", "Arial"))
    secondary = _select_font("ar", "Windows", ("Arial",))
    arbitrary = _select_font("ar", "Windows", ("Fixture Sans",))

    assert primary.family == "Nirmala UI"
    assert not primary.degraded
    assert primary.reason is None
    assert secondary.family == "Arial"
    assert secondary.degraded
    assert secondary.reason == "preferred_font_unavailable"
    assert arbitrary.family == "Fixture Sans"
    assert arbitrary.degraded
    assert arbitrary.reason == "script_font_unavailable"


@pytest.mark.parametrize("language_code", SUPPORTED_LANGUAGE_CODES)
def test_runtime_font_resolution_is_reportable(language_code: str) -> None:
    resolution = resolve_system_font_details(language_code)
    assert resolution.language_code == language_code
    assert resolution.family
    assert resolution.reason is None or resolution.degraded


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows font registration regression")
@pytest.mark.parametrize("language_code", ("hi", "bn", "ar", "ur"))
def test_windows_complex_scripts_use_nirmala_or_report_fallback(language_code: str) -> None:
    resolution = resolve_system_font_details(language_code)
    available = {family.casefold() for family in QFontDatabase.families()}
    if "nirmala ui" in available:
        assert resolution.family == "Nirmala UI"
        assert not resolution.degraded
    else:
        assert resolution.degraded
        assert resolution.reason in {
            "preferred_font_unavailable",
            "script_font_unavailable",
        }
