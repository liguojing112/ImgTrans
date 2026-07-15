from __future__ import annotations

import pytest

from prototypes.rapidocr_multilingual.adapter import scripts_in_text
from prototypes.rapidocr_multilingual.contracts import ContractError, OCRRegion, order_quad


def test_quad_is_normalized_to_top_left_clockwise_order() -> None:
    assert order_quad(((20, 20), (10, 10), (10, 20), (20, 10))) == (
        (10.0, 10.0),
        (20.0, 10.0),
        (20.0, 20.0),
        (10.0, 20.0),
    )


def test_degenerate_quad_is_rejected() -> None:
    with pytest.raises(ContractError):
        order_quad(((0, 0), (1, 1), (2, 2), (3, 3)))


def test_confidence_outside_contract_is_rejected() -> None:
    with pytest.raises(ContractError):
        OCRRegion(
            polygon=order_quad(((0, 0), (10, 0), (10, 10), (0, 10))),
            text="test",
            confidence=1.1,
            language_code="en",
            language_confidence=1.0,
            model_id="test-model",
        )


def test_script_detection_does_not_treat_digits_as_a_language() -> None:
    assert scripts_in_text("商品 ABC العربية हिन्दी ไทย 123") == {
        "Han",
        "Latin",
        "Arabic",
        "Devanagari",
        "Thai",
    }

