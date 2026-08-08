"""第1步：商品来源页 — 链接解析 + 图片上传 + 手动资料表单。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
    parse_requested = Signal(str)  # url

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)

        title = QLabel("第 1 步：商品来源")
        title.setObjectName("stepTitle")
        title.setStyleSheet("color: #212733; font-size: 18px; font-weight: 650;")
        layout.addWidget(title)

        # 链接解析区域
        link_group = QFrame()
        link_group.setStyleSheet(
            "QFrame { background: #f4f5f7; border: 1px solid #d5d9e0;"
            "  border-radius: 6px; padding: 8px; }"
        )
        link_layout = QHBoxLayout(link_group)
        link_layout.setContentsMargins(8, 8, 8, 8)
        link_layout.setSpacing(8)

        self._link_url = QLineEdit()
        self._link_url.setPlaceholderText("粘贴商品链接，如 Amazon / AliExpress / 淘宝 / 京东 ...")
        self._link_url.setStyleSheet(
            "QLineEdit { background: #ffffff; border: 1px solid #d5d9e0;"
            "  color: #212733; padding: 6px 10px; border-radius: 4px; }"
        )
        self._link_url.returnPressed.connect(self._on_parse_clicked)
        link_layout.addWidget(self._link_url, stretch=1)

        self._parse_btn = QPushButton("解析")
        self._parse_btn.setToolTip("解析商品链接，提取标题、描述和图片")
        self._parse_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db); color: #ffffff;"
            "  border: 1px solid #5a9af4; border-radius: 6px;"
            "  padding: 6px 16px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4); border-color: #6aaaf4; }"
            "QPushButton:disabled { background: #ffffff; color: #98a0ad;"
            "  border-color: #d5d9e0; }"
        )
        self._parse_btn.clicked.connect(self._on_parse_clicked)
        link_layout.addWidget(self._parse_btn)

        self._link_status = QLabel("")
        self._link_status.setStyleSheet("color: #626b7a; font-size: 11px;")
        link_layout.addWidget(self._link_status)

        layout.addWidget(link_group)

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
            "  font-size: 14px; font-weight: 600;"
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

    def set_parse_busy(self, busy: bool) -> None:
        """解析进行中时禁用按钮并显示状态。"""
        self._parse_btn.setEnabled(not busy)
        self._parse_btn.setText("解析中..." if busy else "解析")
        if busy:
            self._link_status.setText("正在抓取页面...")
        else:
            self._link_status.setText("")

    def set_parse_hint(self, message: str) -> None:
        """显示人工验证提示（如验证码/登录墙）。"""
        self._link_status.setText(message)
        self._link_status.setStyleSheet("color: #ca8a04; font-size: 11px;")
        self._link_status.setWordWrap(True)

    def set_parse_result(
        self,
        title: str,
        description: str,
        attributes: dict[str, str],
        platform: str,
    ) -> None:
        """将解析结果填入手动资料表单。"""
        current = self._form.get_info()
        updated = ProductManualInfo(
            name=title or current.name,
            brand=attributes.get("品牌", current.brand),
            category=current.category,
            model=attributes.get("型号", current.model),
            specs=attributes.get("规格", current.specs),
            material=attributes.get("材质", current.material),
            color=attributes.get("颜色", current.color),
            scene=current.scene,
            target_market=current.target_market,
            original_description=description or current.original_description,
            notes=current.notes,
        )
        self._form.set_info(updated)
        platform_text = f"[{platform}] " if platform else ""
        self._link_status.setText(f"{platform_text}解析完成 ✓")
        self._link_status.setStyleSheet("color: #626b7a; font-size: 11px;")
        self._link_status.setWordWrap(False)

    def set_parse_error(self, message: str) -> None:
        self._link_status.setText(f"✗ {message}")
        self._link_status.setStyleSheet("color: #dc2626; font-size: 11px;")
        self._link_status.setWordWrap(True)

    def set_parse_idle(self) -> None:
        self._link_status.setText("")
        self._link_status.setStyleSheet("color: #626b7a; font-size: 11px;")
        self._link_status.setWordWrap(False)

    def _on_parse_clicked(self) -> None:
        url = self._link_url.text().strip()
        if not url:
            self.set_parse_error("请输入商品链接")
            return
        self.set_parse_idle()
        self.parse_requested.emit(url)
