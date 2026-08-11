"""第1步：商品来源页 — 图片上传 + 手动资料表单。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from src.domain.product_info import ProductManualInfo, ProductSourceImage
from src.ui.product.widgets.image_uploader import ImageUploader
from src.ui.product.widgets.product_form import ProductForm


class StepSource(QFrame):
    """第1步：商品来源 — 链接解析 + 图片上传 + 资料表单。"""

    next_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)

        title = QLabel("第 1 步：商品来源")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # 左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #ffffff; width: 2px; }"
        )

        left = QFrame()
        left.setObjectName("stepLeftPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self._uploader = ImageUploader()
        left_layout.addWidget(self._uploader)
        splitter.addWidget(left)

        right = QFrame()
        right.setObjectName("stepRightPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(QLabel("手动输入商品资料（可选，可补全 AI 分析不足）"))
        self._form = ProductForm()
        right_layout.addWidget(self._form)
        splitter.addWidget(right)

        splitter.setSizes([380, 420])
        layout.addWidget(splitter, stretch=1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._next_btn = QPushButton("下一步：AI 分析 →")
        self._next_btn.setObjectName("primaryButton")
        self._next_btn.setStyleSheet(
            "QPushButton#primaryButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db);"
            "  color: #ffffff; border: 1px solid #5a9af4;"
            "  border-radius: 8px; padding: 10px 24px;"
            " font-weight: 600;"
            "}"
            "QPushButton#primaryButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4);"
            "  border-color: #6aaaf4;"
            "}"
        )
        self._next_btn.clicked.connect(self.next_requested.emit)
        btn_layout.addWidget(self._next_btn)
        layout.addLayout(btn_layout)

    # —— 公开接口 ——

    def images(self) -> list[ProductSourceImage]:
        return self._uploader.images()

    def manual_info(self) -> ProductManualInfo:
        return self._form.get_info()

    def add_image(self, path: Path) -> None:
        self._uploader.add_image(path)

    def set_images(self, images: list[ProductSourceImage]) -> None:
        for img in images:
            self._uploader.add_image(img.path)

    def set_manual_info(self, info: ProductManualInfo) -> None:
        self._form.set_info(info)

    # —— 页面级拖拽导入 ——

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in supported:
                self._uploader.add_image(path)
