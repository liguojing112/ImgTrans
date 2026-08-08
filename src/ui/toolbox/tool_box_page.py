"""图片工具箱主页面 — 三栏布局：图片列表 | 操作设置 | 预览/导出。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.ui.toolbox.tool_box_model import OperationParams, ToolBoxModel
from src.ui.toolbox.widgets.image_list_panel import ImageListPanel
from src.ui.toolbox.widgets.operation_panel import OperationPanel
from src.ui.toolbox.widgets.preview_panel import PreviewPanel


class ToolBoxPage(QFrame):
    """图片工具箱页面。"""

    back_requested = Signal()
    export_completed = Signal(str)  # 导出完成消息

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("toolBoxPage")
        self.setMinimumSize(1024, 640)
        self.resize(1280, 780)

        self._model = ToolBoxModel()
        self._task_runner: object | None = None
        self._codec: object | None = None
        self._processed: dict[str, Path] = {}  # image_id → processed temp path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部栏
        top_bar = QWidget()
        top_bar.setFixedHeight(44)
        top_bar.setStyleSheet("background: #ffffff;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 4, 12, 4)

        back_btn = QLabel("← 返回首页")
        back_btn.setStyleSheet(
            "QLabel { color: #212733; padding: 4px 12px; }"
            "QLabel:hover { color: #3973db; }"
        )
        back_btn.mousePressEvent = lambda _: self.back_requested.emit()
        top_layout.addWidget(back_btn)

        title = QLabel("图片工具箱")
        title.setObjectName("pageTitle")
        top_layout.addWidget(title)

        top_layout.addStretch()

        status_label = QLabel("")
        status_label.setStyleSheet("color: #000000;")
        self._status_label = status_label
        top_layout.addWidget(status_label)

        layout.addWidget(top_bar)

        # 三栏内容区
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #ffffff; width: 2px; }"
        )

        self._image_list = ImageListPanel(self._model)
        self._operation_panel = OperationPanel()
        self._preview_panel = PreviewPanel(self._model)

        splitter.addWidget(self._image_list)
        splitter.addWidget(self._preview_panel)
        splitter.addWidget(self._operation_panel)
        splitter.setSizes([280, 350, 420])
        layout.addWidget(splitter, stretch=1)

        # 信号连接
        self._operation_panel.apply_requested.connect(self._on_apply_operations)
        self._preview_panel.export_requested.connect(self._on_export)
        self._preview_panel.crop_box_selected.connect(self._on_crop_box_selected)
        self._preview_panel.watermark_selected.connect(self._on_watermark_selected)
        self._preview_panel.watermark_moved.connect(self._on_watermark_moved)
        self._preview_panel.watermark_scaled.connect(self._on_watermark_scaled)
        # 裁剪模式切换 → 预览
        self._operation_panel.crop_mode_changed.connect(
            self._preview_panel.set_crop_mode)
        # 预览取消裁剪（Esc/取消按钮）→ 操作面板按钮状态恢复
        self._preview_panel.crop_mode_exited.connect(
            lambda: self._operation_panel._set_crop_mode_active(False))
        # 水印变化 → 刷新预览水印框
        self._operation_panel.watermarks_changed.connect(self._sync_watermarks_preview)

    def _sync_watermarks_preview(self) -> None:
        self._preview_panel.set_watermarks(self._operation_panel.watermarks())

    # —— 依赖注入 ——

    def _on_crop_box_selected(self, x: int, y: int, w: int, h: int) -> None:
        """拖拽裁剪选区 → 启用裁剪并同步到操作面板。"""
        self._operation_panel.enable_crop(x, y, w, h)

    def _on_watermark_selected(self, wm_id: str) -> None:
        """预览中选中水印 → 同步到操作面板列表。"""
        items = self._operation_panel.watermarks()
        for i, wm in enumerate(items):
            if wm.id == wm_id:
                self._operation_panel._wm_list.setCurrentRow(i)
                break

    def _on_watermark_moved(self, wm_id: str, x: float, y: float) -> None:
        """水印移动后同步到操作面板并刷新预览。"""
        for wm in self._operation_panel.watermarks():
            if wm.id == wm_id:
                wm.custom_x = x
                wm.custom_y = y
                break
        self._preview_panel.set_watermarks(self._operation_panel.watermarks())

    def _on_watermark_scaled(self, wm_id: str, scale: float) -> None:
        """水印缩放后同步。"""
        for wm in self._operation_panel.watermarks():
            if wm.id == wm_id:
                wm.scale = scale
                break
        self._preview_panel.set_watermarks(self._operation_panel.watermarks())

    def set_task_runner(self, runner: object) -> None:
        self._task_runner = runner

    def set_codec(self, codec: object) -> None:
        self._codec = codec

    # —— 批量操作 ——

    def _on_apply_operations(self, params: OperationParams) -> None:
        from src.application.toolbox_operations import apply_operations

        # 应用时自动退出裁剪模式（选区已同步到参数）
        if self._operation_panel._crop_cancel_btn.isVisible():
            self._operation_panel._set_crop_mode_active(False)
            self._preview_panel.set_crop_mode(False)

        images = [img for img in self._model.images if img.selected]
        if not images:
            self._status_label.setText("请先选择至少一张图片")
            self._status_label.setStyleSheet("color: #d97706;")
            return

        if self._task_runner is None:
            self._status_label.setText("任务运行器未初始化")
            return

        self._status_label.setText(f"正在处理 {len(images)} 张图片...")
        self._status_label.setStyleSheet("color: #000000;")

        # 裁剪只作用于当前预览的图片，其他图片跳过裁剪
        preview_id = self._preview_panel.current_preview_id()
        crop_box = params.crop_box

        def _run():
            results = []
            for img in images:
                # 如果之前有处理结果，从处理后的图片继续操作
                source = self._processed.get(img.id) or img.path
                # 非预览图片去掉裁剪参数
                img_params = params
                if crop_box is not None and img.id != preview_id:
                    from dataclasses import replace
                    img_params = replace(params, crop_box=None)
                try:
                    result = apply_operations(source, img_params, codec=self._codec)
                    results.append((img.id, result))
                except Exception as e:
                    import traceback
                    print(f"[ToolBox] 处理失败: {img.path.name}: {e}")
                    traceback.print_exc()
                    results.append((img.id, str(e)))
            return results

        def _on_success(results):
            success_count = sum(1 for _, r in results if isinstance(r, Path))
            fail_count = len(results) - success_count
            if success_count:
                # 缓存处理结果用于预览
                for img_id, r in results:
                    if isinstance(r, Path):
                        self._processed[img_id] = r
                self._preview_panel.set_processed(self._processed)
            if fail_count:
                for img_id, r in results:
                    if isinstance(r, str):
                        img = self._model.get_by_id(img_id)
                        name = img.path.name if img else img_id
                        self._status_label.setText(
                            f"处理完成：{success_count} 张成功，{fail_count} 张失败"
                            f"  —  {name}: {r[:80]}"
                        )
                        break
                self._status_label.setStyleSheet("color: #d97706;")
            else:
                self._status_label.setText(f"处理完成：{success_count} 张图片")
                self._status_label.setStyleSheet("color: #16a34a;")
            self._preview_panel._update_preview()

        def _on_error(error: Exception):
            self._status_label.setText(f"处理失败: {error}")
            self._status_label.setStyleSheet("color: #dc2626;")

        self._task_runner.submit(_run, on_success=_on_success, on_error=_on_error)

    # —— 导出 ——

    def _on_export(self, target_dir: Path) -> None:
        images = [img for img in self._model.images if img.selected]
        if not images:
            self._status_label.setText("请先选择要导出的图片")
            return

        target_dir.mkdir(parents=True, exist_ok=True)
        # Read the current controls at export time.  Previously this used the
        # last apply-operation snapshot, so changing the format afterwards
        # still exported with the old suffix (often the source JPG).
        params = self._operation_panel._build_params()
        from src.application.toolbox_operations import export_image

        fmt = params.output_format
        quality = params.quality
        suffix = self._preview_panel._suffix_spin.value()

        exported = 0
        for i, img in enumerate(images):
            source = self._processed.get(img.id) or img.path
            try:
                export_image(
                    source, target_dir,
                    index=suffix + i,
                    output_format=fmt,
                    quality=quality,
                    codec=self._codec,
                )
                exported += 1
            except Exception:
                pass

        self._status_label.setText(f"已导出 {exported}/{len(images)} 张图片到 {target_dir}")
        self._status_label.setStyleSheet("color: #16a34a;")
        self.export_completed.emit(str(target_dir))
