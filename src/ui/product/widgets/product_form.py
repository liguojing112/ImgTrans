"""商品资料手动输入表单。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.product_info import ProductManualInfo


class ProductForm(QFrame):
    """手动输入商品资料的表单。"""

    info_changed = Signal(object)  # ProductManualInfo

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("productForm")
        self._fields: dict[str, QLineEdit | QPlainTextEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        clear_btn = QPushButton("清空")
        clear_btn.setToolTip("清空所有已填写的手动资料")
        clear_btn.setStyleSheet(
            "QPushButton { background: #ffffff; color: #626b7a;"
            "  padding: 3px 12px; border: 1px solid #d5d9e0; border-radius: 4px; }"
            "QPushButton:hover { background: #eef0f4; color: #212733; }"
        )
        clear_btn.clicked.connect(self.clear_all)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        form = QFormLayout(scroll_widget)
        form.setSpacing(8)

        field_defs = [
            ("name", "商品名称 *", QLineEdit),
            ("brand", "品牌", QLineEdit),
            ("category", "商品类别", QLineEdit),
            ("model", "型号", QLineEdit),
            ("specs", "规格", QLineEdit),
            ("material", "材质", QLineEdit),
            ("color", "颜色", QLineEdit),
            ("scene", "适用场景", QLineEdit),
            ("target_market", "目标市场", QLineEdit),
        ]
        for key, label, cls in field_defs:
            widget = cls()
            widget.setPlaceholderText(f"输入{label}")
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(lambda _: self._emit_info())
            form.addRow(label, widget)
            self._fields[key] = widget

        # 描述
        desc = QPlainTextEdit()
        desc.setPlaceholderText("输入原始商品描述")
        desc.setMaximumHeight(100)
        desc.textChanged.connect(lambda: self._emit_info())
        form.addRow("原始描述", desc)
        self._fields["original_description"] = desc

        # 备注
        notes = QPlainTextEdit()
        notes.setPlaceholderText("输入其他备注信息")
        notes.setMaximumHeight(80)
        notes.textChanged.connect(lambda: self._emit_info())
        form.addRow("备注", notes)
        self._fields["notes"] = notes

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def get_info(self) -> ProductManualInfo:
        def _text(key: str) -> str:
            w = self._fields.get(key)
            if w is None:
                return ""
            if isinstance(w, QPlainTextEdit):
                return w.toPlainText().strip()
            return w.text().strip()

        return ProductManualInfo(
            name=_text("name"),
            brand=_text("brand"),
            category=_text("category"),
            model=_text("model"),
            specs=_text("specs"),
            material=_text("material"),
            color=_text("color"),
            scene=_text("scene"),
            target_market=_text("target_market"),
            original_description=_text("original_description"),
            notes=_text("notes"),
        )

    def set_info(self, info: ProductManualInfo) -> None:
        mapping = {
            "name": info.name,
            "brand": info.brand,
            "category": info.category,
            "model": info.model,
            "specs": info.specs,
            "material": info.material,
            "color": info.color,
            "scene": info.scene,
            "target_market": info.target_market,
            "original_description": info.original_description,
            "notes": info.notes,
        }
        for key, widget in self._fields.items():
            value = mapping.get(key, "")
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
            elif isinstance(widget, QLineEdit):
                widget.setText(value)

    def _emit_info(self) -> None:
        self.info_changed.emit(self.get_info())

    def clear_all(self) -> None:
        """清空所有字段。"""
        for widget in self._fields.values():
            if isinstance(widget, QPlainTextEdit):
                widget.clear()
            elif isinstance(widget, QLineEdit):
                widget.clear()
