"""商品事实编辑器 — 可编辑表格，每个字段可确认/标记不确定。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.product_info import ProductFact


class FactEditor(QFrame):
    """商品事实可编辑表格。"""

    fact_changed = Signal(str, str)  # field_name, new_value
    fact_confirmed = Signal(str)     # field_name
    fact_uncertain = Signal(str)     # field_name

    _FIELD_LABELS: dict[str, str] = {
        "name": "商品名称",
        "brand": "品牌",
        "model": "型号",
        "specs": "规格",
        "color": "颜色",
        "material": "材质",
        "package_quantity": "包装数量",
        "target_audience": "适用对象",
        "usage_scene": "使用场景",
        "main_functions": "主要功能",
        "visible_accessories": "可见配件",
    }

    _SOURCE_DISPLAY: dict[str, str] = {
        "手动": "手动",
        "手动修改": "编辑",
        "AI推断": "AI",
        "商品链接": "链接",
        "OCR识别": "OCR",
        "图片理解": "视觉",
        "用户输入": "用户",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("factEditor")
        self._rows: dict[str, _FactRow] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._container_layout = QVBoxLayout(container)
        self._container_layout.setSpacing(4)
        self._container_layout.addStretch()

        for field_name, label in self._FIELD_LABELS.items():
            row = _FactRow(label, field_name)
            row.value_changed.connect(self._on_value_changed)
            row.confirmed.connect(self._on_confirmed)
            row.uncertain.connect(self._on_uncertain)
            self._rows[field_name] = row
            self._container_layout.insertWidget(
                self._container_layout.count() - 1, row
            )

        scroll.setWidget(container)
        layout.addWidget(scroll)

    def set_fact(self, fact: ProductFact) -> None:
        for field_name, row in self._rows.items():
            value = fact.field_value(field_name)
            source = fact.source.get(field_name, "")
            confirmed = fact.confirmed.get(field_name, False)
            uncertain = fact.uncertain.get(field_name, False)
            source_label = self._SOURCE_DISPLAY.get(source, source)
            row.set_value(value, source_label, confirmed, uncertain)

    def _on_value_changed(self, field_name: str, value: str) -> None:
        self.fact_changed.emit(field_name, value)

    def _on_confirmed(self, field_name: str) -> None:
        self.fact_confirmed.emit(field_name)

    def _on_uncertain(self, field_name: str) -> None:
        self.fact_uncertain.emit(field_name)


class _FactRow(QFrame):
    """单行事实字段。"""

    value_changed = Signal(str, str)
    confirmed = Signal(str)
    uncertain = Signal(str)

    def __init__(self, label: str, field_name: str) -> None:
        super().__init__()
        self._field_name = field_name
        self.setProperty("editorStyle", True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        # 标签
        lbl = QLabel(label)
        lbl.setFixedWidth(80)
        lbl.setStyleSheet("color: #9898b0; font-size: 12px;")
        layout.addWidget(lbl)

        # 值
        self._value_edit = QLineEdit()
        self._value_edit.setPlaceholderText("未识别")
        self._value_edit.textChanged.connect(
            lambda t: self.value_changed.emit(self._field_name, t)
        )
        layout.addWidget(self._value_edit, stretch=1)

        # 来源
        self._source_label = QLabel()
        self._source_label.setFixedWidth(50)
        self._source_label.setStyleSheet("color: #686878; font-size: 10px;")
        layout.addWidget(self._source_label)

        # 确认按钮
        self._confirm_btn = QPushButton("✓")
        self._confirm_btn.setFixedSize(28, 28)
        self._confirm_btn.setToolTip("确认此信息")
        self._confirm_btn.setStyleSheet(
            "QPushButton { border: 1px solid #3d3d5c; border-radius: 4px;"
            "  color: #4dff4d; font-size: 14px; }"
            "QPushButton:hover { background: #2a4a2a; }"
        )
        self._confirm_btn.clicked.connect(
            lambda: self.confirmed.emit(self._field_name)
        )
        layout.addWidget(self._confirm_btn)

        # 不确定按钮
        self._uncertain_btn = QPushButton("⚠")
        self._uncertain_btn.setFixedSize(28, 28)
        self._uncertain_btn.setToolTip("标记为不确定")
        self._uncertain_btn.setStyleSheet(
            "QPushButton { border: 1px solid #3d3d5c; border-radius: 4px;"
            "  color: #ffaa00; font-size: 14px; }"
            "QPushButton:hover { background: #4a3a2a; }"
        )
        self._uncertain_btn.clicked.connect(
            lambda: self.uncertain.emit(self._field_name)
        )
        layout.addWidget(self._uncertain_btn)

    def set_value(
        self, value: str, source: str, confirmed: bool, uncertain: bool
    ) -> None:
        self._value_edit.setText(value)
        self._source_label.setText(source)
        if confirmed:
            self._value_edit.setStyleSheet("border: 1px solid #4dff4d;")
            self._uncertain_btn.setVisible(False)
        elif uncertain:
            self._value_edit.setStyleSheet("border: 1px solid #ffaa00;")
            self._confirm_btn.setVisible(True)
        else:
            self._value_edit.setStyleSheet("")
