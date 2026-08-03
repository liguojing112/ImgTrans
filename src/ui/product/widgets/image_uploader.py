"""图片上传组件 — 拖拽 + 缩略图列表 + 用途设置。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.product_info import ProductSourceImage

_PURPOSE_LABELS = {
    "main": "商品主图",
    "detail": "细节图",
    "packaging": "包装图",
    "specs": "参数图",
    "scene": "场景图",
    "reference": "参考图",
}


class ImageUploader(QFrame):
    """图片上传组件 — 上传按钮 + 缩略图列表 + 删除/排序/用途设置。"""

    images_changed = Signal(list)  # list[ProductSourceImage]

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("imageUploader")
        self.setAcceptDrops(True)
        self._images: list[ProductSourceImage] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 按钮
        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("+ 添加图片")
        self._add_btn.setMinimumHeight(48)
        self._add_btn.setStyleSheet(
            "QPushButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            "  border-radius: 10px; padding: 12px 32px;"
            "  font-size: 15px; font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #6aaaf4;"
            "}"
        )
        self._clear_btn = QPushButton("清空")
        self._clear_btn.setMinimumHeight(48)
        self._clear_btn.setStyleSheet(
            "QPushButton {"
            "  background: #2a2a3e; color: #9898b0; font-size: 15px;"
            "  padding: 12px 24px; border: 1px solid #3d3d5c; border-radius: 8px;"
            "}"
            "QPushButton:hover { background: #363650; color: #e0e0f0; }"
        )
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        btn_layout.addWidget(self._add_btn)
        btn_layout.addWidget(self._clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 缩略图列表
        self._list = QListWidget()
        self._list.setObjectName("thumbnailList")
        self._list.setIconSize(self._list.iconSize().scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio))
        self._list.setDragDropMode(self._list.dragDropMode().InternalMove)
        self._list.model().rowsMoved.connect(self._on_reorder)
        self._list.itemDoubleClicked.connect(self._on_preview)
        layout.addWidget(self._list, stretch=1)

    def images(self) -> list[ProductSourceImage]:
        return list(self._images)

    def add_image(self, path: Path) -> None:
        img = ProductSourceImage(
            id=str(uuid.uuid4()),
            path=path,
            purpose="main" if not self._images else "detail",
            is_primary=len(self._images) == 0,
            order=len(self._images),
        )
        self._images.append(img)
        self._refresh_list()
        self.images_changed.emit(self.images())

    def _refresh_list(self) -> None:
        self._list.clear()
        for img in self._images:
            item_widget = self._make_item_widget(img)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.ItemDataRole.UserRole, img.id)
            self._list.addItem(list_item)
            self._list.setItemWidget(list_item, item_widget)

    def _make_item_widget(self, img: ProductSourceImage) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # 缩略图
        thumb = QLabel()
        pixmap = QPixmap(str(img.path))
        thumb.setPixmap(pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        thumb.setFixedSize(48, 48)
        layout.addWidget(thumb)

        # 文件名
        name = QLabel(img.path.name)
        name.setStyleSheet("color: #e0e0f0; font-size: 12px;")
        layout.addWidget(name, stretch=1)

        # 主图标记
        if img.is_primary:
            primary = QLabel("主图")
            primary.setStyleSheet(
                "color: #3973db; font-size: 11px; font-weight: bold;"
            )
            layout.addWidget(primary)

        # 用途下拉
        purpose_combo = QComboBox()
        for key, label in _PURPOSE_LABELS.items():
            purpose_combo.addItem(label, key)
        purpose_combo.setCurrentText(_PURPOSE_LABELS.get(img.purpose, "细节图"))
        purpose_combo.currentIndexChanged.connect(
            lambda idx, i=img: self._on_purpose_changed(i, purpose_combo.itemData(idx))
        )
        layout.addWidget(purpose_combo)

        # 删除按钮
        del_btn = QPushButton("×")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(
            "QPushButton { border: none; color: #ff6b6b; font-size: 14px; }"
            "QPushButton:hover { color: #ff3b3b; }"
        )
        del_btn.clicked.connect(lambda: self._on_remove(img.id))
        layout.addWidget(del_btn)

        return widget

    def _on_purpose_changed(self, img: ProductSourceImage, purpose: str) -> None:
        img.purpose = purpose

    def _on_remove(self, image_id: str) -> None:
        self._images = [img for img in self._images if img.id != image_id]
        if self._images:
            self._images[0].is_primary = True
        self._refresh_list()
        self.images_changed.emit(self.images())

    def _on_reorder(self) -> None:
        new_order: list[ProductSourceImage] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            img_id = item.data(Qt.ItemDataRole.UserRole)
            for img in self._images:
                if img.id == img_id:
                    img.order = i
                    img.is_primary = (i == 0)
                    new_order.append(img)
                    break
        self._images = new_order
        self._refresh_list()
        self.images_changed.emit(self.images())

    def _on_preview(self, item: QListWidgetItem) -> None:
        img_id = item.data(Qt.ItemDataRole.UserRole)
        for img in self._images:
            if img.id == img_id:
                dlg = QDialog(self)
                dlg.setWindowTitle(img.path.name)
                dlg.setMinimumSize(400, 300)
                dlg.setStyleSheet("background: #1a1a2e;")
                layout = QVBoxLayout(dlg)
                pixmap = QPixmap(str(img.path))
                if not pixmap.isNull():
                    screen_size = dlg.screen().availableSize()
                    max_w = int(screen_size.width() * 0.6)
                    max_h = int(screen_size.height() * 0.7)
                    pixmap = pixmap.scaled(max_w, max_h,
                                           Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                label = QLabel()
                label.setPixmap(pixmap)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(label)
                dlg.exec()
                break

    def _on_add_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QSplitter
        dialog = QFileDialog(self, "选择商品图片", os.path.expanduser("~"))
        dialog.setNameFilter("图片文件 (*.jpg *.jpeg *.png *.webp *.bmp);;所有文件 (*.*)")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.resize(1000, 600)
        # 调整左侧树宽：找到 QSplitter 设置比例
        sp = dialog.findChild(QSplitter)
        if sp:
            sp.setSizes([200, 800])
        if dialog.exec() == QFileDialog.DialogCode.Accepted:
            for path in sorted(dialog.selectedFiles(), key=lambda p: Path(p).name.casefold()):
                self.add_image(Path(path))

    def _on_clear_clicked(self) -> None:
        self._images.clear()
        self._list.clear()
        self.images_changed.emit(self.images())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in supported:
                self.add_image(path)
