"""图片工具箱 — 右侧预览 + 导出面板。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFrame,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from src.ui.toolbox.tool_box_model import ToolBoxModel
from src.ui.toolbox.widgets.watermark_preview import InteractivePreview


class PreviewPanel(QFrame):
    """右侧面板：预览当前图片 + 导出设置。"""

    export_requested = Signal(object)  # target_dir: Path
    crop_box_selected = Signal(int, int, int, int)  # x, y, w, h
    crop_mode_exited = Signal()  # 取消/退出裁剪模式
    watermark_selected = Signal(str)
    watermark_moved = Signal(str, float, float)
    watermark_scaled = Signal(str, float)

    def __init__(self, model: ToolBoxModel) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._model = model
        self._processed: dict[str, Path] = {}  # image_id → processed temp path
        self._current_preview_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        title = QLabel("预览 / 导出")
        title.setStyleSheet("color: #212733; font-size: 16px; font-weight: 650;")
        layout.addWidget(title)

        # 预览区域（占满剩余空间）
        preview_group = QGroupBox("当前预览")
        preview_group.setStyleSheet(
            "QGroupBox { color: #626b7a; font-size: 12px; border: 1px solid #d5d9e0;"
            "  border-radius: 6px; margin-top: 8px; padding-top: 12px; }"
        )
        preview_layout = QVBoxLayout(preview_group)

        self._preview_label = InteractivePreview()
        self._preview_label.setMinimumHeight(220)
        self._preview_label.setStyleSheet(
            "QLabel { background: #e6e8ec; border: 1px dashed #d5d9e0;"
            "  border-radius: 6px; color: #98a0ad; font-size: 12px; }"
        )
        self._preview_label.setWordWrap(True)
        self._preview_label.crop_box_changed.connect(self.crop_box_selected.emit)
        self._preview_label.crop_mode_exited.connect(self.crop_mode_exited.emit)
        self._preview_label.watermark_selected.connect(self.watermark_selected.emit)
        self._preview_label.watermark_moved.connect(self.watermark_moved.emit)
        self._preview_label.watermark_scaled.connect(self.watermark_scaled.emit)
        preview_layout.addWidget(self._preview_label, stretch=1)

        self._preview_info = QLabel("")
        self._preview_info.setStyleSheet("color: #98a0ad; font-size: 11px;")
        preview_layout.addWidget(self._preview_info)
        layout.addWidget(preview_group, stretch=1)

        # 导出设置
        export_group = QGroupBox("导出设置")
        export_group.setStyleSheet(preview_group.styleSheet())
        export_form = QFormLayout(export_group)
        export_form.setSpacing(6)

        self._target_dir = QLineEdit()
        self._target_dir.setPlaceholderText("选择导出文件夹")
        self._target_dir.setStyleSheet(
            "QLineEdit { background: #ffffff; color: #212733; border: 1px solid #d5d9e0;"
            "  padding: 4px 8px; border-radius: 4px; font-size: 12px; }"
        )
        browse_btn = QPushButton("浏览...")
        browse_btn.setFixedSize(60, 24)
        browse_btn.setStyleSheet(
            "QPushButton { background: #ffffff; color: #626b7a; border: 1px solid #d5d9e0;"
            "  font-size: 11px; border-radius: 4px; } QPushButton:hover { color: #212733; }"
        )
        browse_btn.clicked.connect(self._on_browse_target)
        target_row = QHBoxLayout()
        target_row.addWidget(self._target_dir)
        target_row.addWidget(browse_btn)
        target_widget = QWidget()
        target_widget.setLayout(target_row)
        export_form.addRow("目标文件夹:", target_widget)

        # 文件名起始序号
        suffix_container, self._suffix_spin = self._make_spin(0, 99999, 0, 100)
        self._suffix_spin.setPrefix("IMG_")
        self._suffix_spin.setToolTip("输出文件名前缀序号")
        export_form.addRow("文件名起始序号:", suffix_container)

        layout.addWidget(export_group)

        # 导出按钮（顶到底部）
        export_btn = QPushButton(" 导出选中图片")
        export_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db); color: #ffffff;"
            "  border: 1px solid #5a9af4; border-radius: 8px;"
            "  padding: 10px 20px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4); border-color: #6aaaf4; }"
            "QPushButton:disabled { background: #ffffff; color: #98a0ad;"
            "  border-color: #d5d9e0; }"
        )
        export_btn.clicked.connect(self._on_export)
        layout.addWidget(export_btn)
        # 底部无弹性空间 → 导出按钮始终贴底

        self._model.selection_changed.connect(self._update_preview)
        self._model.images_changed.connect(self._update_preview)

    @staticmethod
    def _make_spin(min_v: int, max_v: int, default: int, width: int = 80) -> tuple:
        """创建无按钮的 SpinBox + 外部 ± 按钮（图层状态样式），返回 (QWidget, QSpinBox)。"""
        container = QWidget()
        # 防止被 QFormLayout 拉伸导致按钮与输入框分离
        from PySide6.QtWidgets import QSizePolicy
        container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(2)

        spin = QSpinBox()
        spin.setRange(min_v, max_v)
        spin.setValue(default)
        spin.setFixedWidth(width)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setStyleSheet(
            "QSpinBox { background: #ffffff; color: #212733; border: 1px solid #d5d9e0;"
            "  padding: 4px 6px; border-radius: 4px; font-size: 12px; }"
        )
        hbox.addWidget(spin)

        btn_smaller = QToolButton()
        btn_smaller.setText("−")
        btn_smaller.setToolTip("减小")
        btn_smaller.setFixedSize(22, 16)
        btn_smaller.setStyleSheet(
            "QToolButton { background: #2a2a44; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px; font-size: 11px; }"
            "QToolButton:hover { background: #34345a; }"
            "QToolButton:pressed { background: #3a3a5e; }"
        )
        btn_smaller.clicked.connect(spin.stepDown)
        hbox.addWidget(btn_smaller)

        btn_larger = QToolButton()
        btn_larger.setText("+")
        btn_larger.setToolTip("增大")
        btn_larger.setFixedSize(22, 16)
        btn_larger.setStyleSheet(
            "QToolButton { background: #2a2a44; color: #212733;"
            "  border: 1px solid #d5d9e0; border-radius: 4px; font-size: 11px; }"
            "QToolButton:hover { background: #34345a; }"
            "QToolButton:pressed { background: #3a3a5e; }"
        )
        btn_larger.clicked.connect(spin.stepUp)
        hbox.addWidget(btn_larger)

        return container, spin

    def _on_browse_target(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(self, "选择导出文件夹")
        if folder:
            self._target_dir.setText(folder)

    def _on_export(self) -> None:
        target = self._target_dir.text().strip()
        if not target:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先选择导出文件夹。")
            return
        self.export_requested.emit(Path(target))

    def set_processed(self, processed: dict[str, Path]) -> None:
        """缓存处理结果路径。"""
        self._processed = processed

    def set_watermarks(self, items: list) -> None:
        """设置预览中的水印框。"""
        self._preview_label.set_items(items)
        self._preview_label.update()

    def set_crop_mode(self, active: bool) -> None:
        """进入/退出裁剪模式。"""
        self._preview_label.set_crop_mode(active)

    def current_preview_id(self) -> str | None:
        """当前预览的图片 id（裁剪只作用于该图）。"""
        return self._current_preview_id

    def _update_preview(self) -> None:
        self._current_preview_id: str | None = None
        for img in self._model.images:
            if img.selected:
                # 记录当前预览的图片 id（裁剪只作用于该图）
                self._current_preview_id = img.id
                # 优先显示处理后的图片
                source = self._processed.get(img.id) or img.path
                try:
                    orig = QPixmap(str(source))
                    # 保存原始尺寸用于裁剪坐标映射
                    self._preview_label.set_original_size(
                        orig.width(), orig.height())
                    pw = self._preview_label.width()
                    ph = self._preview_label.height()
                    pix = orig.scaled(
                        max(pw - 4, 1), max(ph - 4, 1),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._preview_label.setPixmap(pix)
                    self._preview_label.setText("")
                    suffix = " (已处理)" if img.id in self._processed else ""
                    self._preview_info.setText(
                        f"{img.path.name}{suffix}  ({orig.width()}×{orig.height()})"
                    )
                except Exception:
                    self._preview_label.setText("无法加载预览")
                    self._preview_info.setText("")
                return
        self._preview_label.setText("请先选择图片")
        self._preview_label.setPixmap(None)
        self._preview_info.setText("")
