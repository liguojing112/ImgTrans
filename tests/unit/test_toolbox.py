"""图片工具箱单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from src.ui.toolbox.tool_box_model import (
    OperationParams,
    ToolBoxImage,
    ToolBoxModel,
    WatermarkItem,
)


class TestToolBoxModel:
    def test_add_image(self):
        model = ToolBoxModel()
        model.add_image(Path("/tmp/test.png"))
        assert model.total_count == 1
        assert model.selected_count == 1

    def test_add_duplicate_image(self):
        model = ToolBoxModel()
        model.add_image(Path("/tmp/test.png"))
        model.add_image(Path("/tmp/test.png"))
        assert model.total_count == 1

    def test_remove_image(self):
        model = ToolBoxModel()
        model.add_image(Path("/tmp/a.png"))
        model.add_image(Path("/tmp/b.png"))
        img_id = model.images[0].id
        model.remove_image(img_id)
        assert model.total_count == 1

    def test_remove_selected(self):
        model = ToolBoxModel()
        model.add_image(Path("/tmp/a.png"))
        model.add_image(Path("/tmp/b.png"))
        model.images[0].selected = True
        model.images[1].selected = False
        model.remove_selected()
        assert model.total_count == 1
        assert not model.images[0].selected

    def test_clear_all(self):
        model = ToolBoxModel()
        model.add_image(Path("/tmp/a.png"))
        model.add_image(Path("/tmp/b.png"))
        model.clear_all()
        assert model.total_count == 0

    def test_select_deselect_all(self):
        model = ToolBoxModel()
        model.add_image(Path("/tmp/a.png"))
        model.add_image(Path("/tmp/b.png"))
        model.deselect_all()
        assert model.selected_count == 0
        model.select_all()
        assert model.selected_count == 2

    def test_set_selected(self):
        model = ToolBoxModel()
        model.add_image(Path("/tmp/a.png"))
        img_id = model.images[0].id
        model.set_selected(img_id, False)
        assert model.selected_count == 0


class TestOperationParams:
    def test_defaults(self):
        p = OperationParams()
        assert p.crop_box is None
        assert p.rotate_deg == 0
        assert p.flip is None
        assert p.output_format is None
        assert p.quality == 95
        assert p.max_size is None
        assert p.watermarks == []
        assert p.watermark_image_path is None

    def test_custom_values(self):
        p = OperationParams(
            crop_box=(0, 0, 100, 100),
            rotate_deg=90,
            flip="horizontal",
            output_format="webp",
            quality=80,
            max_size=(800, 600),
            watermarks=[
                WatermarkItem(id="wm1", text="水印A", color="#FF0000",
                              opacity=0.5, position="top_left",
                              flip_h=True, scale=1.5,
                              custom_x=0.2, custom_y=0.8),
            ],
        )
        assert p.crop_box == (0, 0, 100, 100)
        assert p.rotate_deg == 90
        assert p.flip == "horizontal"
        assert p.output_format == "webp"
        assert p.quality == 80
        assert p.max_size == (800, 600)
        assert len(p.watermarks) == 1
        wm = p.watermarks[0]
        assert wm.text == "水印A"
        assert wm.color == "#FF0000"
        assert wm.flip_h is True
        assert wm.flip_v is False
        assert wm.scale == 1.5
        assert wm.custom_x == 0.2
        assert wm.custom_y == 0.8


class TestWatermarkItem:
    def test_defaults(self):
        wm = WatermarkItem(id="wm1")
        assert wm.text == "水印"
        assert wm.font_size == 80
        assert wm.color == "#00FF00"
        assert wm.opacity == 0.55
        assert wm.tiled is False
        assert wm.flip_h is False
        assert wm.flip_v is False
        assert wm.position == "bottom_right"
        assert wm.custom_x is None
        assert wm.custom_y is None
        assert wm.scale == 1.0


class TestToolBoxOperations:
    def test_imports(self):
        from src.application.toolbox_operations import apply_operations, export_image
        assert callable(apply_operations)
        assert callable(export_image)
