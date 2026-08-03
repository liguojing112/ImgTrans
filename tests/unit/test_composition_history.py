import pytest

from src.domain.composition import (
    AddLayerCommand,
    CompositionError,
    CompositionSession,
    DeleteLayerCommand,
    ReplaceLayerCommand,
)
from src.application.coordinate_transform import CoordinateTransform
from src.domain.composition import CropViewport
from src.domain.layout import PathPoint, TextBox, TextLayer, TextLayout, TextStyle


def _layer(region_id: str, text: str) -> TextLayer:
    return TextLayer(
        region_id,
        text,
        TextBox(50, 30, 80, 24),
        TextStyle("Fixture Sans", 18, (10, 20, 30)),
    )


def test_execute_undo_redo_and_new_branch_clears_redo() -> None:
    original = _layer("r1", "原译文")
    first = _layer("r1", "第一次修改")
    second = _layer("r1", "第二次修改")
    session = CompositionSession(TextLayout((original,)))
    session.execute(ReplaceLayerCommand(original, first))
    assert session.layout.layer_by_id("r1").text == "第一次修改"
    assert session.can_undo and not session.can_redo
    session.undo()
    assert session.layout.layer_by_id("r1") == original
    assert session.can_redo
    session.redo()
    assert session.layout.layer_by_id("r1") == first
    session.undo()
    session.execute(ReplaceLayerCommand(original, second))
    assert session.layout.layer_by_id("r1") == second
    assert not session.can_redo


def test_history_is_bounded_and_rejects_stale_command() -> None:
    original = _layer("r1", "0")
    session = CompositionSession(TextLayout((original,)), history_limit=2)
    one = _layer("r1", "1")
    two = _layer("r1", "2")
    three = _layer("r1", "3")
    session.execute(ReplaceLayerCommand(original, one))
    session.execute(ReplaceLayerCommand(one, two))
    session.execute(ReplaceLayerCommand(two, three))
    session.undo()
    session.undo()
    with pytest.raises(CompositionError) as empty:
        session.undo()
    assert empty.value.code == "nothing_to_undo"
    with pytest.raises(CompositionError) as stale:
        session.execute(ReplaceLayerCommand(original, three))
    assert stale.value.code == "stale_edit"


def test_layout_requires_unique_layer_ids() -> None:
    with pytest.raises(ValueError):
        TextLayout((_layer("same", "A"), _layer("same", "B")))


def test_add_and_delete_commands_round_trip_layer_order() -> None:
    first = _layer("first", "A")
    second = _layer("second", "B")
    session = CompositionSession(TextLayout((first,)))
    session.execute(AddLayerCommand(second, 1))
    assert [layer.region_id for layer in session.layout.layers] == ["first", "second"]
    session.undo()
    assert session.layout.layers == (first,)
    session.redo()
    session.execute(DeleteLayerCommand(first, 0))
    assert session.layout.layers == (second,)
    session.undo()
    assert session.layout.layers == (first, second)


def test_coordinate_transform_round_trips_original_canvas_and_view() -> None:
    transform = CoordinateTransform(CropViewport(40, 25, 300, 200), 1.5, 12, 8)
    original = PathPoint(90, 70)
    canvas = transform.original_to_canvas(original)
    assert canvas == PathPoint(50, 45)
    assert transform.canvas_to_original(canvas) == original
    view = transform.canvas_to_view(canvas)
    assert transform.view_to_canvas(view) == canvas
    box = TextBox(100, 80, 50, 20, 17)
    assert transform.canvas_box_to_original(
        transform.original_box_to_canvas(box)
    ) == box
