"""编辑器状态中心。

非 MVVM 架构 — 仅作为信号驱动的状态聚合器。
持有当前图片文档、文字图层集合、翻译结果和编辑合成器引用。
支持多文档（批量图片可一一进入工作台）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from src.domain.image import ImageDocument
from src.domain.layout import TextLayer, TextLayout


@dataclass
class EditorDocumentRef:
    """工作台中的一个文档条目（对应一张图片）。

    除来源信息外还保存该文档的编辑状态，切换文档时由 EditorModel
    负责快照/恢复，避免翻译结果等状态跨文档丢失。
    """

    doc_id: str
    name: str
    source_path: Path
    source_document: ImageDocument
    ocr_result: object = None
    translation_result: object = None
    text_layout: TextLayout = field(default_factory=lambda: TextLayout(()))
    composition_editor: object = None
    rendered_document: ImageDocument | None = None
    repaired_background: ImageDocument | None = None
    is_dirty: bool = False


class EditorModel(QObject):
    """编辑器核心状态容器，通过信号驱动 view / property_panel 同步。"""

    document_changed = Signal(object)  # ImageDocument | None
    text_layout_changed = Signal(object)  # TextLayout
    selected_layer_changed = Signal(object)  # TextLayer | None
    translation_started = Signal()
    translation_stage_changed = Signal(object)  # ImageStage
    translation_finished = Signal(object)  # TranslateImageResult
    translation_failed = Signal(str)  # error message
    edit_finished = Signal(object)  # CompositionEditResult
    edit_failed = Signal(str)
    showing_original_changed = Signal(bool)
    preview_mode_changed = Signal(str)
    ocr_started = Signal()
    ocr_finished = Signal(object)  # OcrResult
    documents_changed = Signal()  # 文档列表变化
    active_document_changed = Signal(str)  # doc_id

    def __init__(self) -> None:
        super().__init__()
        self._document: ImageDocument | None = None
        self._source_document: ImageDocument | None = None
        self._text_layout = TextLayout(())
        self._selected_layer_id: str | None = None
        self._zoom_factor = 1.0
        self._translating = False
        self._showing_original = False
        self._preview_mode = "layers"
        self._layers_visible = True
        self._ocr_result: object = None  # OcrResult | None
        self._translation_result: object = None  # TranslateImageResult | None
        self._is_dirty = False
        self._composition_editor: object = None  # EditComposition | None
        self._rendered_document: ImageDocument | None = None
        self._repaired_background: ImageDocument | None = None
        self._ocr_elapsed_ms = 0.0
        self._translation_elapsed_ms = 0.0
        # 多文档
        self._documents: list[EditorDocumentRef] = []
        self._active_document_id: str | None = None

    # —— 多文档 ——

    def add_document(
        self,
        source_path: Path,
        source_document: ImageDocument,
        name: str | None = None,
        rendered_document: ImageDocument | None = None,
    ) -> str:
        """把一张图片加入工作台文档列表，返回 doc_id。

        加入前先保存当前活动文档的编辑状态；新文档以干净状态激活。
        传入 rendered_document（如已完成的批量翻译成品）时，画布直接
        显示译文图，原图保留为对比图。
        """
        self._snapshot_active()
        doc_id = str(uuid4())
        ref = EditorDocumentRef(
            doc_id=doc_id,
            name=name or source_path.name,
            source_path=source_path,
            source_document=source_document,
            rendered_document=rendered_document,
        )
        self._documents.append(ref)
        self._active_document_id = doc_id
        self._restore_active()
        self.documents_changed.emit()
        self.active_document_changed.emit(doc_id)
        return doc_id

    def remove_document(self, doc_id: str) -> None:
        self._documents = [d for d in self._documents if d.doc_id != doc_id]
        if self._active_document_id == doc_id:
            self._active_document_id = (
                self._documents[-1].doc_id if self._documents else None
            )
            if self._active_document_id:
                self._restore_active()
                self.active_document_changed.emit(self._active_document_id)
        self.documents_changed.emit()

    def clear_documents(self) -> None:
        self._documents.clear()
        self._active_document_id = None
        self.documents_changed.emit()

    def documents(self) -> list[EditorDocumentRef]:
        return list(self._documents)

    @property
    def active_document_id(self) -> str | None:
        return self._active_document_id

    def set_active_document(self, doc_id: str) -> None:
        if doc_id == self._active_document_id:
            return
        if not any(d.doc_id == doc_id for d in self._documents):
            return
        self._snapshot_active()
        self._active_document_id = doc_id
        self._restore_active()
        self.active_document_changed.emit(doc_id)

    def active_document(self) -> EditorDocumentRef | None:
        for d in self._documents:
            if d.doc_id == self._active_document_id:
                return d
        return None

    # —— 文档编辑状态快照 ——

    def _snapshot_active(self) -> None:
        """把当前全局编辑状态保存到活动文档条目。"""
        ref = self.active_document()
        if ref is None:
            return
        ref.ocr_result = self._ocr_result
        ref.translation_result = self._translation_result
        ref.text_layout = self._text_layout
        ref.composition_editor = self._composition_editor
        ref.rendered_document = self._rendered_document
        ref.repaired_background = self._repaired_background
        ref.is_dirty = self._is_dirty

    def _restore_active(self) -> None:
        """从活动文档条目恢复全局编辑状态（直接赋值，不发射信号）。"""
        ref = self.active_document()
        if ref is None:
            return
        self._ocr_result = ref.ocr_result
        self._translation_result = ref.translation_result
        self._text_layout = ref.text_layout
        self._composition_editor = ref.composition_editor
        self._rendered_document = ref.rendered_document
        self._repaired_background = ref.repaired_background
        self._is_dirty = ref.is_dirty
        self._selected_layer_id = None

    # —— document ——

    @property
    def document(self) -> ImageDocument | None:
        return self._document

    @document.setter
    def document(self, value: ImageDocument | None) -> None:
        if value is self._document:
            return
        self._document = value
        self.document_changed.emit(value)

    @property
    def source_document(self) -> ImageDocument | None:
        return self._source_document

    @source_document.setter
    def source_document(self, value: ImageDocument | None) -> None:
        self._source_document = value

    # —— text_layout ——

    @property
    def text_layout(self) -> TextLayout:
        return self._text_layout

    @text_layout.setter
    def text_layout(self, value: TextLayout) -> None:
        if value is not self._text_layout:
            self._text_layout = value
            self.text_layout_changed.emit(value)
            if self._selected_layer_id is not None:
                try:
                    value.layer_by_id(self._selected_layer_id)
                except KeyError:
                    self.selected_layer_id = None

    # —— selected_layer_id ——

    @property
    def selected_layer_id(self) -> str | None:
        return self._selected_layer_id

    @selected_layer_id.setter
    def selected_layer_id(self, region_id: str | None) -> None:
        if region_id == self._selected_layer_id:
            return
        self._selected_layer_id = region_id
        layer = None
        if region_id is not None:
            try:
                layer = self._text_layout.layer_by_id(region_id)
            except KeyError:
                self._selected_layer_id = None
        self.selected_layer_changed.emit(layer)

    @property
    def selected_layer(self) -> TextLayer | None:
        if self._selected_layer_id is None:
            return None
        try:
            return self._text_layout.layer_by_id(self._selected_layer_id)
        except KeyError:
            return None

    # —— ocr_result ——

    @property
    def ocr_result(self) -> object | None:
        return self._ocr_result

    @ocr_result.setter
    def ocr_result(self, value: object | None) -> None:
        self._ocr_result = value

    # —— translation ——

    @property
    def translating(self) -> bool:
        return self._translating

    @translating.setter
    def translating(self, value: bool) -> None:
        self._translating = value

    # —— dirty ——

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    @is_dirty.setter
    def is_dirty(self, value: bool) -> None:
        self._is_dirty = value

    @property
    def translation_result(self) -> object | None:
        return self._translation_result

    @translation_result.setter
    def translation_result(self, value: object | None) -> None:
        self._translation_result = value

    # —— elapsed ——

    @property
    def ocr_elapsed_ms(self) -> float:
        return self._ocr_elapsed_ms

    @ocr_elapsed_ms.setter
    def ocr_elapsed_ms(self, value: float) -> None:
        self._ocr_elapsed_ms = value

    @property
    def translation_elapsed_ms(self) -> float:
        return self._translation_elapsed_ms

    @translation_elapsed_ms.setter
    def translation_elapsed_ms(self, value: float) -> None:
        self._translation_elapsed_ms = value

    # —— composition ——

    @property
    def composition_editor(self) -> object | None:
        return self._composition_editor

    @composition_editor.setter
    def composition_editor(self, value: object | None) -> None:
        self._composition_editor = value

    @property
    def rendered_document(self) -> ImageDocument | None:
        return self._rendered_document

    @rendered_document.setter
    def rendered_document(self, value: ImageDocument | None) -> None:
        self._rendered_document = value

    @property
    def repaired_background(self) -> ImageDocument | None:
        return self._repaired_background

    @repaired_background.setter
    def repaired_background(self, value: ImageDocument | None) -> None:
        self._repaired_background = value

    # —— showing_original ——

    @property
    def showing_original(self) -> bool:
        return self._showing_original

    @showing_original.setter
    def showing_original(self, value: bool) -> None:
        if value == self._showing_original:
            return
        self._showing_original = value
        self.showing_original_changed.emit(value)

    # —— 预览模式 ——

    @property
    def preview_mode(self) -> str:
        return self._preview_mode

    @preview_mode.setter
    def preview_mode(self, value: str) -> None:
        if value == self._preview_mode:
            return
        self._preview_mode = value
        self.preview_mode_changed.emit(value)

    # —— layers_visible ——

    @property
    def layers_visible(self) -> bool:
        return self._layers_visible

    @layers_visible.setter
    def layers_visible(self, value: bool) -> None:
        self._layers_visible = value

    # —— zoom ——

    @property
    def zoom_factor(self) -> float:
        return self._zoom_factor

    @zoom_factor.setter
    def zoom_factor(self, value: float) -> None:
        self._zoom_factor = max(0.1, min(20.0, value))

    # —— 图层操作方法 ——

    def replace_layer(self, before: TextLayer, after: TextLayer) -> None:
        self.text_layout = self._text_layout.replace_layer(after)
        if self._selected_layer_id == before.region_id:
            self._selected_layer_id = after.region_id
            self.selected_layer_changed.emit(after)

    def add_layer(self, layer: TextLayer) -> None:
        self.text_layout = self._text_layout.add_layer(
            layer, len(self._text_layout.layers)
        )

    def remove_layer(self, region_id: str) -> None:
        layout, _, _ = self._text_layout.remove_layer(region_id)
        self.text_layout = layout
