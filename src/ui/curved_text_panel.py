from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.layout import ArcTextPath, PathPoint, TextLayer, default_arc_path


class CurvedTextPanel(QFrame):
    apply_requested = Signal()
    straight_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("curvedTextPanel")
        self._layer: TextLayer | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        title = QLabel("弧形文字路径")
        title.setObjectName("panelTitle")
        hint = QLabel("三个控制点使用原图坐标；也可直接拖动画布上的绿色控制点。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        self.selected_label = QLabel("尚未选择文字图层")
        self.selected_label.setObjectName("curveSelectedLabel")
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.selected_label)

        form = QFormLayout()
        self.start = _PointFields()
        self.control = _PointFields()
        self.end = _PointFields()
        self.reverse = QCheckBox("反向排列")
        form.addRow("起点 X/Y", self.start)
        form.addRow("控制点 X/Y", self.control)
        form.addRow("终点 X/Y", self.end)
        form.addRow("", self.reverse)
        layout.addLayout(form)

        self.default_button = QPushButton("生成默认上弧路径")
        self.default_button.setObjectName("defaultCurveButton")
        self.apply_button = QPushButton("应用控制点")
        self.apply_button.setObjectName("applyCurveButton")
        self.straight_button = QPushButton("恢复直线排版")
        self.straight_button.setObjectName("removeCurveButton")
        self.default_button.clicked.connect(self._apply_default)
        self.apply_button.clicked.connect(self.apply_requested.emit)
        self.straight_button.clicked.connect(self.straight_requested.emit)
        actions = QHBoxLayout()
        actions.addWidget(self.apply_button)
        actions.addWidget(self.straight_button)
        layout.addWidget(self.default_button)
        layout.addLayout(actions)
        self.status_label = QLabel("选择文字图层后可转换为弧形文字")
        self.status_label.setObjectName("curveStatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.set_layer(None)

    @property
    def selected_region_id(self) -> str | None:
        return self._layer.region_id if self._layer else None

    @property
    def edited_path(self) -> ArcTextPath:
        return ArcTextPath(
            self.start.point,
            self.control.point,
            self.end.point,
            self.reverse.isChecked(),
        )

    def set_layer(self, layer: TextLayer | None) -> None:
        self._layer = layer
        if layer is None:
            self.selected_label.setText("尚未选择文字图层")
            self.status_label.setText("选择文字图层后可转换为弧形文字")
        else:
            self.selected_label.setText(f"当前图层：{layer.text or '（空文本）'}")
            path = layer.path or default_arc_path(layer.box)
            self._set_path(path)
            self.status_label.setText(
                "当前为弧形排版，可继续调整"
                if layer.path is not None
                else "当前为直线排版，可生成默认弧线或编辑控制点"
            )
        self.set_editor_available(layer is not None, False)

    def set_editor_available(self, available: bool, busy: bool) -> None:
        enabled = available and self._layer is not None and not busy
        self.default_button.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        self.straight_button.setEnabled(
            enabled and self._layer is not None and self._layer.path is not None
        )

    def _set_path(self, path: ArcTextPath) -> None:
        self.start.set_point(path.start)
        self.control.set_point(path.control)
        self.end.set_point(path.end)
        self.reverse.setChecked(path.reverse)

    def _apply_default(self) -> None:
        if self._layer is None:
            return
        self._set_path(default_arc_path(self._layer.box))
        self.apply_requested.emit()


class _PointFields(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.x = _coordinate_spin()
        self.y = _coordinate_spin()
        layout.addWidget(self.x)
        layout.addWidget(self.y)

    @property
    def point(self) -> PathPoint:
        return PathPoint(self.x.value(), self.y.value())

    def set_point(self, point: PathPoint) -> None:
        self.x.setValue(point.x)
        self.y.setValue(point.y)


def _coordinate_spin() -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setRange(-100000, 100000)
    control.setDecimals(1)
    control.setSuffix(" px")
    return control
