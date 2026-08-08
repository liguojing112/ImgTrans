"""图片工具箱 — 左侧图片列表面板（多选、拖拽导入、缩略图）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.toolbox.tool_box_model import ToolBoxImage, ToolBoxModel


class ImageListPanel(QFrame):
    """左侧面板：图片列表 + 导入/清空/全选按钮。"""

    def __init__(self, model: ToolBoxModel) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self._model = model
        self._thumb_size = 48

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = QPushButton("+ 添加图片")
        add_btn.clicked.connect(self._on_add_clicked)
        add_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #4a8af4, stop:1 #3973db); color: #fff;"
            "  border: 1px solid #5a9af4; border-radius: 6px;"
            "  padding: 6px 12px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #5a9af4, stop:1 #4a8af4); border-color: #6aaaf4; }"
        )
        add_folder_btn = QPushButton("+ 添加文件夹")
        add_folder_btn.clicked.connect(self._on_add_folder_clicked)
        add_folder_btn.setStyleSheet(
            "QPushButton { background: #ffffff; color: #626b7a; font-size: 12px;"
            "  padding: 6px 12px; border: 1px solid #d5d9e0; border-radius: 4px; }"
            "QPushButton:hover { background: #eef0f4; color: #212733; }"
        )
        btn_row.addWidget(add_btn)
        btn_row.addWidget(add_folder_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 全选 / 清空
        ctrl_row = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(lambda: self._model.select_all())
        select_all_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #626b7a; font-size: 11px;"
            "  border: 1px solid #d5d9e0; padding: 3px 10px; border-radius: 4px; }"
            "QPushButton:hover { background: #eef0f4; color: #212733; }"
        )
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda: self._model.clear_all())
        clear_btn.setStyleSheet(select_all_btn.styleSheet())
        remove_btn = QPushButton("移除选中")
        remove_btn.clicked.connect(lambda: self._model.remove_selected())
        remove_btn.setStyleSheet(select_all_btn.styleSheet())
        ctrl_row.addWidget(select_all_btn)
        ctrl_row.addWidget(remove_btn)
        ctrl_row.addWidget(clear_btn)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # 图片列表
        self._list = QListWidget()
        self._list.setAcceptDrops(True)
        self._list.setStyleSheet(
            "QListWidget { background: #e6e8ec; border: 1px solid #d5d9e0;"
            "  border-radius: 6px; color: #212733; }"
        )
        layout.addWidget(self._list, stretch=1)

        # 统计信息
        self._stats_label = QLabel("0 张图片")
        self._stats_label.setStyleSheet("color: #98a0ad; font-size: 11px;")
        layout.addWidget(self._stats_label)

        self._model.images_changed.connect(self._refresh)
        self._model.selection_changed.connect(self._update_stats)
        self._update_stats()

    # —— 导入 ——

    def _on_add_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.webp *.bmp)",
        )
        self._model.add_images([Path(p) for p in paths])

    def _on_add_folder_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not folder:
            return
        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        paths = [
            Path(folder) / f.name
            for f in Path(folder).iterdir()
            if f.is_file() and f.suffix.lower() in valid_exts
        ]
        self._model.add_images(paths)

    # —— 拖拽 ——

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            path = Path(p)
            if path.is_file() and path.suffix.lower() in valid_exts:
                paths.append(path)
        if paths:
            self._model.add_images(paths)

    # —— 刷新 ——

    def _refresh(self) -> None:
        self._list.clear()
        for img in self._model.images:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, img.id)

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(8)

            check = QCheckBox()
            check.setChecked(img.selected)
            check.setStyleSheet(
                "QCheckBox { spacing: 0; } QCheckBox::indicator { width: 16px; height: 16px; }"
            )
            check.toggled.connect(
                lambda checked, iid=img.id: self._model.set_selected(iid, checked)
            )
            row_layout.addWidget(check)

            thumb = QLabel()
            try:
                pix = QPixmap(str(img.path))
                pix = pix.scaled(
                    self._thumb_size, self._thumb_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                thumb.setPixmap(pix)
            except Exception:
                thumb.setText("✗")
            thumb.setFixedSize(self._thumb_size, self._thumb_size)
            thumb.setStyleSheet(
                "QLabel { background: #ffffff; border: 1px solid #d5d9e0; border-radius: 4px; }"
            )
            row_layout.addWidget(thumb)

            name_label = QLabel(img.path.name)
            name_label.setStyleSheet("color: #212733; font-size: 11px;")
            name_label.setWordWrap(False)
            row_layout.addWidget(name_label, stretch=1)

            del_btn = QPushButton("×")
            del_btn.setFixedSize(20, 20)
            del_btn.setStyleSheet(
                "QPushButton { border: none; color: #dc2626; font-size: 14px; }"
                "QPushButton:hover { color: #ff3b3b; }"
            )
            del_btn.clicked.connect(
                lambda _, iid=img.id: self._model.remove_image(iid)
            )
            row_layout.addWidget(del_btn)

            item.setSizeHint(row.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)

        self._update_stats()

    def _update_stats(self) -> None:
        total = self._model.total_count
        selected = self._model.selected_count
        if total == 0:
            self._stats_label.setText("拖拽图片到此处开始")
        elif selected == total:
            self._stats_label.setText(f"全部选中：{total} 张")
        else:
            self._stats_label.setText(f"共 {total} 张，已选 {selected} 张")
