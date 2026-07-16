import pytest

from src.domain.composition import (
    ApplyManualRegionCommand,
    BackgroundPatch,
    CompositionSession,
)
from src.domain.layout import TextBox, TextLayer, TextLayout, TextStyle
from src.domain.manual_region import ManualInputMode, ManualRegionSpec, box_to_quad


def _layer() -> TextLayer:
    return TextLayer(
        "manual-1",
        "译文",
        TextBox(40, 30, 50, 20),
        TextStyle("Arial", 12, (0, 0, 0)),
    )


def test_manual_spec_requires_text_for_direct_modes() -> None:
    box = TextBox(40, 30, 50, 20)
    with pytest.raises(ValueError):
        ManualRegionSpec(ManualInputMode.SOURCE_TEXT, box, box, box)
    with pytest.raises(ValueError):
        ManualRegionSpec(ManualInputMode.TRANSLATED_TEXT, box, box, box)
    assert ManualRegionSpec(
        ManualInputMode.TRANSLATED_TEXT,
        box,
        box,
        box,
        translated_text="译文",
    ).translated_text == "译文"


def test_box_to_quad_preserves_center_and_rotation() -> None:
    points = box_to_quad(TextBox(40, 30, 20, 10, 90))
    assert sum(point.x for point in points) / 4 == pytest.approx(40)
    assert sum(point.y for point in points) / 4 == pytest.approx(30)
    assert max(point.y for point in points) - min(point.y for point in points) == pytest.approx(20)


def test_manual_patch_and_layer_share_one_undo_command() -> None:
    session = CompositionSession(TextLayout(()))
    patch = BackgroundPatch("patch-1", 10, 15, 2, 2, "RGB", bytes(12))
    command = ApplyManualRegionCommand(_layer(), patch, 0)
    session.execute(command)
    assert session.layout.layer_by_id("manual-1").text == "译文"
    assert session.state.patches == (patch,)
    session.undo()
    assert session.layout.layers == ()
    assert session.state.patches == ()
    session.redo()
    assert session.state.patches == (patch,)
