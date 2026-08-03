"""图片工具箱状态模型 — 图片列表 + 操作参数 + 选中状态。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal


@dataclass
class ToolBoxImage:
    """工具箱中的单张图片。"""

    id: str
    path: Path
    selected: bool = True
    processed: bool = False


@dataclass
class WatermarkItem:
    """一组水印（文字水印）。"""

    id: str
    text: str = "水印"
    font_family: str = "sans-serif"
    font_size: int = 80
    color: str = "#00FF00"
    opacity: float = 0.55
    tiled: bool = False
    flip_h: bool = False
    flip_v: bool = False
    position: str = "bottom_right"  # 九宫格
    # 拖拽后的自定义位置（0-1 相对图片坐标）；None 表示用九宫格位置
    custom_x: float | None = None
    custom_y: float | None = None
    # 缩放比例（相对默认尺寸）
    scale: float = 1.0


@dataclass
class OperationParams:
    """批量操作参数。"""

    # 裁剪：None 表示不裁剪；(x, y, w, h) 像素坐标
    crop_box: tuple[int, int, int, int] | None = None
    # 旋转：0 / 90 / 180 / 270
    rotate_deg: int = 0
    # 翻转：None / "horizontal" / "vertical"
    flip: str | None = None
    # 输出格式：None 表示保持原格式
    output_format: str | None = None  # "png" / "jpg" / "webp" / "gif" / "tiff"
    # 压缩质量 1-100（仅 JPEG/WEBP 有效）
    quality: int = 95
    # 输出尺寸：None 表示保持原尺寸；(max_width, max_height)
    max_size: tuple[int, int] | None = None
    # 多组水印
    watermarks: list[WatermarkItem] = field(default_factory=list)
    # 图片水印路径（可选，跟随第一组文字水印一起应用）
    watermark_image_path: Path | None = None


class ToolBoxModel(QObject):
    """工具箱页面状态模型。"""

    images_changed = Signal()
    selection_changed = Signal()
    params_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._images: list[ToolBoxImage] = []
        self.params = OperationParams()

    # —— 图片列表 ——

    @property
    def images(self) -> list[ToolBoxImage]:
        return list(self._images)

    def add_image(self, path: Path) -> None:
        # 去重
        existing_paths = {img.path.resolve() for img in self._images}
        if path.resolve() in existing_paths:
            return
        self._images.append(ToolBoxImage(id=str(uuid.uuid4()), path=path))
        self.images_changed.emit()

    def add_images(self, paths: list[Path]) -> None:
        for p in paths:
            self.add_image(p)

    def remove_image(self, image_id: str) -> None:
        self._images = [img for img in self._images if img.id != image_id]
        self.images_changed.emit()

    def remove_selected(self) -> None:
        self._images = [img for img in self._images if not img.selected]
        self.images_changed.emit()

    def clear_all(self) -> None:
        self._images.clear()
        self.images_changed.emit()

    def set_selected(self, image_id: str, selected: bool) -> None:
        for img in self._images:
            if img.id == image_id:
                img.selected = selected
                self.selection_changed.emit()
                return

    def select_all(self) -> None:
        for img in self._images:
            img.selected = True
        self.selection_changed.emit()

    def deselect_all(self) -> None:
        for img in self._images:
            img.selected = False
        self.selection_changed.emit()

    @property
    def selected_count(self) -> int:
        return sum(1 for img in self._images if img.selected)

    @property
    def total_count(self) -> int:
        return len(self._images)

    # —— 操作参数 ——

    def set_params(self, params: OperationParams) -> None:
        self.params = params
        self.params_changed.emit()

    # —— 查询 ——

    def get_by_id(self, image_id: str) -> ToolBoxImage | None:
        for img in self._images:
            if img.id == image_id:
                return img
        return None
