"""商品详情生成 — 状态聚合器。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from src.domain.product_info import (
    ProductAnalysisResult,
    ProductManualInfo,
    ProductSourceImage,
)
from src.domain.copywriting import CopywritingResult


class ProductModel(QObject):
    """商品详情生成状态聚合器 — 信号驱动。"""

    step_changed = Signal(int)
    images_changed = Signal(list)  # list[ProductSourceImage]
    manual_info_changed = Signal(object)  # ProductManualInfo
    analysis_started = Signal()
    analysis_finished = Signal(object)  # ProductAnalysisResult
    analysis_failed = Signal(str)
    copywriting_started = Signal()
    copywriting_finished = Signal(object)  # CopywritingResult
    copywriting_failed = Signal(str)
    dirty_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._current_step = 0
        self._images: list[ProductSourceImage] = []
        self._manual_info = ProductManualInfo()
        self._analysis_result: ProductAnalysisResult | None = None
        self._copywriting_result: CopywritingResult | None = None
        self._is_dirty = False

    # —— current_step ——

    @property
    def current_step(self) -> int:
        return self._current_step

    @current_step.setter
    def current_step(self, value: int) -> None:
        if value == self._current_step:
            return
        self._current_step = value
        self.step_changed.emit(value)

    # —— images ——

    @property
    def images(self) -> list[ProductSourceImage]:
        return self._images

    @images.setter
    def images(self, value: list[ProductSourceImage]) -> None:
        self._images = value
        self.images_changed.emit(value)

    def add_image(self, image: ProductSourceImage) -> None:
        self._images.append(image)
        self.images_changed.emit(self._images)
        self._is_dirty = True
        self.dirty_changed.emit(True)

    def remove_image(self, image_id: str) -> None:
        self._images = [img for img in self._images if img.id != image_id]
        self.images_changed.emit(self._images)
        self._is_dirty = True
        self.dirty_changed.emit(True)

    # —— manual_info ——

    @property
    def manual_info(self) -> ProductManualInfo:
        return self._manual_info

    @manual_info.setter
    def manual_info(self, value: ProductManualInfo) -> None:
        self._manual_info = value
        self.manual_info_changed.emit(value)
        self._is_dirty = True
        self.dirty_changed.emit(True)

    # —— analysis_result ——

    @property
    def analysis_result(self) -> ProductAnalysisResult | None:
        return self._analysis_result

    @analysis_result.setter
    def analysis_result(self, value: ProductAnalysisResult | None) -> None:
        self._analysis_result = value

    # —— copywriting_result ——

    @property
    def copywriting_result(self) -> CopywritingResult | None:
        return self._copywriting_result

    @copywriting_result.setter
    def copywriting_result(self, value: CopywritingResult | None) -> None:
        self._copywriting_result = value

    # —— is_dirty ——

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    @is_dirty.setter
    def is_dirty(self, value: bool) -> None:
        if value == self._is_dirty:
            return
        self._is_dirty = value
        self.dirty_changed.emit(value)
