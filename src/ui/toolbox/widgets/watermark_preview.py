"""交互式图片预览 — 截图工具式裁剪 + 水印框（选中/移动/缩放）。

裁剪模式（截图工具交互）：
- 点击"裁剪"进入模式；按下拖动绘制蓝色半透明遮罩选区
- 选区四角小方块可拖拽调整；选区整体可拖拽移动
- 双击选区确认裁剪；Esc 或"取消"退出模式
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QSize, Signal
from PySide6.QtGui import (
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication, QLabel

from src.ui.toolbox.tool_box_model import WatermarkItem


class InteractivePreview(QLabel):
    """图片预览 — 裁剪选区（截图工具式）+ 水印框交互。"""

    crop_box_changed = Signal(int, int, int, int)  # x, y, w, h（图片像素）
    crop_mode_exited = Signal()  # 取消/退出裁剪模式
    watermark_selected = Signal(str)  # watermark id
    watermark_moved = Signal(str, float, float)  # id, custom_x, custom_y
    watermark_scaled = Signal(str, float)  # id, scale

    _HANDLE_SIZE = 8

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._items: list[WatermarkItem] = []
        self._orig_width = 1
        self._orig_height = 1
        self._selected_id: str | None = None
        self._watermark_image: QPixmap | None = None
        # 裁剪模式
        self._crop_mode = False
        self._crop_rect: QRect | None = None  # 选区（Label 坐标）
        self._crop_drag: str | None = None  # "draw" / "move" / "tl" "tr" "bl" "br"
        self._crop_drag_start: QPoint | None = None
        self._crop_orig_rect: QRect | None = None
        # 裁剪完成后的选区（Label 坐标），用于裁剪效果预览
        self._crop_preview_rect: QRect | None = None
        # 旋转/翻转预览
        self._transform_deg: int = 0
        self._transform_flip: str | None = None
        # 水印拖拽
        self._wm_drag: str | None = None  # "move" / "scale"
        self._wm_drag_start: QPoint | None = None
        self._wm_drag_item: str | None = None
        self._wm_orig_custom: tuple[float, float] | None = None
        # 缩放 / 平移（预览交互与翻译画布一致：滚轮缩放 + 拖拽移动 + 双击复位）
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_start: QPoint | None = None
        self._left_pan_candidate: QPoint | None = None
        self._left_pan_active = False
        self._MIN_ZOOM = 0.2
        self._MAX_ZOOM = 20.0

    # —— 数据 ——

    def set_items(self, items: list[WatermarkItem]) -> None:
        self._items = list(items)
        self.update()

    def set_original_size(self, w: int, h: int) -> None:
        self._orig_width = max(1, w)
        self._orig_height = max(1, h)

    def set_image(self, pixmap: QPixmap) -> None:
        """设置原始（全分辨率）预览图，并复位缩放/平移。"""
        self.setPixmap(pixmap)
        self._orig_width = max(1, pixmap.width())
        self._orig_height = max(1, pixmap.height())
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_start = None
        self._left_pan_candidate = None
        self._left_pan_active = False
        self.update()

    def set_selected(self, wm_id: str | None) -> None:
        self._selected_id = wm_id
        self.update()

    def set_watermark_image(self, path: str | None) -> None:
        """设置图片水印路径，预览时真实渲染（无路径则清除）。"""
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                self._watermark_image = pix
                self.update()
                return
        self._watermark_image = None
        self.update()

    # —— 裁剪模式 ——

    def set_crop_mode(self, active: bool) -> None:
        """进入/退出裁剪模式。"""
        self._crop_mode = active
        if not active:
            self._crop_rect = None
            self._crop_drag = None
        else:
            # 重新框选前恢复原图预览；裁剪在适配视图下进行，避免缩放/平移干扰选区
            self._crop_preview_rect = None
            self._zoom = 1.0
            self._pan = QPoint(0, 0)
            self._panning = False
            self._pan_start = None
            self._left_pan_candidate = None
            self._left_pan_active = False
        self.update()

    def clear_crop_preview(self) -> None:
        """应用/取消后恢复原图预览。"""
        self._crop_preview_rect = None
        self.update()

    def set_transform_preview(self, rotate_deg: int, flip: str | None) -> None:
        """旋转/翻转效果预览（0°/None 恢复原图）。"""
        self._transform_deg = rotate_deg or 0
        self._transform_flip = flip
        self.update()

    def is_crop_mode(self) -> bool:
        return self._crop_mode

    def cancel_crop(self) -> None:
        """取消裁剪：清除选区并退出模式。"""
        self._crop_rect = None
        self._crop_drag = None
        self.set_crop_mode(False)
        self.crop_mode_exited.emit()
        self.update()

    # —— 键盘 ——

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._crop_mode and event.key() == Qt.Key.Key_Escape:
            self.cancel_crop()
            event.accept()
            return
        super().keyPressEvent(event)

    # —— 缩放 / 平移 ——

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.pixmap() or self._crop_mode:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = 1.0 + abs(delta) / 1200.0
        f = factor if delta > 0 else 1.0 / factor
        self._zoom_about(event.position().toPoint(), f)
        event.accept()

    def _zoom_about(self, pos: QPoint, f: float) -> None:
        """以 pos（Label 坐标）为锚点缩放 f 倍，保持锚点下的像素不动。"""
        new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, self._zoom * f))
        f = new_zoom / self._zoom
        if abs(f - 1.0) < 1e-4:
            return
        cr_center = self.contentsRect().center()
        center = QPoint(
            cr_center.x() + self._pan.x(), cr_center.y() + self._pan.y()
        )
        nc = QPoint(
            round(pos.x() * (1 - f) + center.x() * f),
            round(pos.y() * (1 - f) + center.y() * f),
        )
        self._pan = QPoint(nc.x() - cr_center.x(), nc.y() - cr_center.y())
        self._zoom = new_zoom
        self._clamp_pan()
        self.update()

    def reset_view(self) -> None:
        """复位缩放/平移（回到适配视图）。"""
        if self._zoom == 1.0 and self._pan == QPoint(0, 0):
            return
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self._clamp_pan()
        self.update()

    def zoom_factor(self) -> float:
        return self._zoom

    def _fit_size(self) -> tuple[int, int]:
        """适配视图（zoom=1）下图片的显示尺寸。"""
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return 0, 0
        cr = self.contentsRect()
        avail_w = cr.width() - 4
        avail_h = cr.height() - 4
        if avail_w <= 0 or avail_h <= 0:
            return pix.width(), pix.height()
        ratio = min(avail_w / max(1, pix.width()), avail_h / max(1, pix.height()))
        return max(1, round(pix.width() * ratio)), max(1, round(pix.height() * ratio))

    def _clamp_pan(self) -> None:
        """约束平移量，保证图片始终有一部分可见。"""
        fw, fh = self._fit_size()
        cr = self.contentsRect()
        if fw <= 0 or fh <= 0 or cr.width() <= 0 or cr.height() <= 0:
            self._pan = QPoint(0, 0)
            return
        keep = 40
        dw = max(1, round(fw * self._zoom))
        dh = max(1, round(fh * self._zoom))
        base_x = (cr.width() - dw) // 2
        base_y = (cr.height() - dh) // 2
        self._pan = QPoint(
            self._clamp_axis(self._pan.x(), base_x, dw, cr.width(), keep),
            self._clamp_axis(self._pan.y(), base_y, dh, cr.height(), keep),
        )

    @staticmethod
    def _clamp_axis(pan: int, base: int, disp: int, span: int, keep: int) -> int:
        # 实际左上角 ax = base + pan；约束 ax ∈ [keep - disp, span - keep]
        lo = keep - disp - base
        hi = span - keep - base
        if lo > hi:
            lo, hi = hi, lo
        return max(lo, min(hi, pan))

    # —— 鼠标事件 ——

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # 中键拖动 = 平移（非裁剪模式下）
        if event.button() == Qt.MouseButton.MiddleButton:
            if self.pixmap() and not self._crop_mode:
                self._panning = True
                self._pan_start = event.pos()
                self._left_pan_candidate = None
                self._left_pan_active = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
            return
        if not self.pixmap():
            return
        pos = event.pos()
        if self._crop_mode:
            self._on_crop_press(pos)
            return
        # 非裁剪模式：水印交互
        if self._selected_id and self._hit_handle(pos):
            self._wm_drag = "scale"
            self._wm_drag_item = self._selected_id
            self._wm_drag_start = pos
            self._left_pan_candidate = None
            return
        wm_id = self._hit_watermark(pos)
        if wm_id:
            self._selected_id = wm_id
            self.watermark_selected.emit(wm_id)
            self._wm_drag = "move"
            self._wm_drag_item = wm_id
            self._wm_drag_start = pos
            self._wm_orig_custom = self._get_custom(wm_id)
            self._left_pan_candidate = None
            self.update()
            return
        self._selected_id = None
        self.watermark_selected.emit("")
        # 空白处左键按下：可作为平移起点（超过拖拽阈值才生效）
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_pan_candidate = pos
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.pixmap():
            return
        pos = event.pos()
        # 中键平移
        if self._panning and self._pan_start is not None:
            self._pan += pos - self._pan_start
            self._pan_start = pos
            self._clamp_pan()
            event.accept()
            self.update()
            return
        # 左键空白平移（超过拖拽阈值后）
        if (
            self._left_pan_candidate is not None
            and self._wm_drag is None
            and not self._crop_mode
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            if not self._left_pan_active:
                if (
                    pos - self._left_pan_candidate
                ).manhattanLength() >= QApplication.startDragDistance():
                    self._left_pan_active = True
                    self._pan_start = pos
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._left_pan_active:
                self._pan += pos - self._pan_start
                self._pan_start = pos
                self._clamp_pan()
                event.accept()
                self.update()
                return
        if self._crop_mode and self._crop_drag:
            self._on_crop_drag(pos)
            return
        if self._wm_drag == "move" and self._wm_drag_start:
            dx = pos.x() - self._wm_drag_start.x()
            dy = pos.y() - self._wm_drag_start.y()
            self._move_selected(dx, dy)
        elif self._wm_drag == "scale" and self._wm_drag_start:
            dx = pos.x() - self._wm_drag_start.x()
            self._scale_selected(dx)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # 中键平移结束
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        # 左键平移结束 / 空白单击
        if event.button() == Qt.MouseButton.LeftButton:
            if self._left_pan_active:
                self._left_pan_active = False
                self._pan_start = None
                self._left_pan_candidate = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
                event.accept()
                return
            self._left_pan_candidate = None
        # 裁剪拖拽结束 → 同步选区到参数；新建选区（draw）松开即完成裁剪并退出模式
        if self._crop_mode and self._crop_rect is not None and self._crop_drag:
            rect = self._crop_to_image(self._crop_rect)
            if rect:
                self.crop_box_changed.emit(rect.x(), rect.y(),
                                           rect.width(), rect.height())
            if self._crop_drag == "draw":
                # 一次拖动即完成裁剪：选区有效则保存预览并自动退出裁剪模式
                if rect is not None and rect.width() >= 2 and rect.height() >= 2:
                    self._crop_preview_rect = QRect(self._crop_rect)
                    self.set_crop_mode(False)
                    self.crop_mode_exited.emit()
        self._crop_drag = None
        self._crop_drag_start = None
        self._crop_orig_rect = None
        self._wm_drag = None
        self._wm_drag_item = None
        self._wm_drag_start = None
        self._wm_orig_custom = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """裁剪模式：双击选区确认裁剪；非裁剪模式：双击复位缩放/平移。"""
        if self._crop_mode:
            if not self._crop_rect:
                super().mouseDoubleClickEvent(event)
                return
            if self._crop_rect.contains(event.pos()):
                rect = self._crop_to_image(self._crop_rect)
                if rect:
                    self.crop_box_changed.emit(rect.x(), rect.y(),
                                               rect.width(), rect.height())
                # 确认后退出裁剪模式
                self.set_crop_mode(False)
                self.crop_mode_exited.emit()
                self.update()
                event.accept()
            return
        self.reset_view()
        event.accept()

    # —— 裁剪交互 ——

    def _on_crop_press(self, pos: QPoint) -> None:
        rect = self._crop_rect
        if rect:
            handle = self._hit_crop_handle(pos, rect)
            if handle:
                self._crop_drag = handle
                self._crop_drag_start = pos
                self._crop_orig_rect = QRect(rect)
                return
            if rect.adjusted(-4, -4, 4, 4).contains(pos):
                self._crop_drag = "move"
                self._crop_drag_start = pos
                self._crop_orig_rect = QRect(rect)
                return
        # 空白 → 开始绘制新选区
        self._crop_drag = "draw"
        self._crop_drag_start = pos
        self._crop_rect = QRect(pos, pos)
        self.update()

    def _on_crop_drag(self, pos: QPoint) -> None:
        if self._crop_drag == "draw" and self._crop_drag_start:
            x1 = min(self._crop_drag_start.x(), pos.x())
            y1 = min(self._crop_drag_start.y(), pos.y())
            x2 = max(self._crop_drag_start.x(), pos.x())
            y2 = max(self._crop_drag_start.y(), pos.y())
            self._crop_rect = QRect(x1, y1, x2 - x1, y2 - y1)
        elif self._crop_drag in ("move", "tl", "tr", "bl", "br") and self._crop_orig_rect:
            self._resize_or_move_crop(pos)
        self.update()

    def _resize_or_move_crop(self, pos: QPoint) -> None:
        orig = self._crop_orig_rect
        if orig is None:
            return
        dx = pos.x() - self._crop_drag_start.x()
        dy = pos.y() - self._crop_drag_start.y()
        if self._crop_drag == "move":
            self._crop_rect = QRect(
                orig.x() + dx, orig.y() + dy,
                orig.width(), orig.height(),
            )
            return
        x1, y1, x2, y2 = orig.left(), orig.top(), orig.right(), orig.bottom()
        if "l" in self._crop_drag:
            x1 = min(orig.right() - 1, orig.left() + dx)
        if "r" in self._crop_drag:
            x2 = max(orig.left() + 1, orig.right() + dx)
        if "t" in self._crop_drag:
            y1 = min(orig.bottom() - 1, orig.top() + dy)
        if "b" in self._crop_drag:
            y2 = max(orig.top() + 1, orig.bottom() + dy)
        self._crop_rect = QRect(x1, y1, x2 - x1, y2 - y1)

    @staticmethod
    def _hit_crop_handle(pos: QPoint, rect: QRect) -> str | None:
        handles = {
            "tl": rect.topLeft(), "tr": rect.topRight(),
            "bl": rect.bottomLeft(), "br": rect.bottomRight(),
        }
        for name, corner in handles.items():
            if (abs(pos.x() - corner.x()) <= 8
                    and abs(pos.y() - corner.y()) <= 8):
                return name
        return None

    def _crop_to_image(self, rect: QRect) -> QRect | None:
        """裁剪选区（Label 坐标）→ 图片像素坐标。"""
        img_rect = self._image_draw_rect()
        if img_rect is None or img_rect.width() <= 0 or img_rect.height() <= 0:
            return None
        x1 = max(img_rect.x(), min(rect.left(), img_rect.right()))
        y1 = max(img_rect.y(), min(rect.top(), img_rect.bottom()))
        x2 = max(img_rect.x(), min(rect.right(), img_rect.right()))
        y2 = max(img_rect.y(), min(rect.bottom(), img_rect.bottom()))
        if x2 <= x1 or y2 <= y1:
            return None
        scale_x = self._orig_width / img_rect.width()
        scale_y = self._orig_height / img_rect.height()
        return QRect(
            int((x1 - img_rect.x()) * scale_x),
            int((y1 - img_rect.y()) * scale_y),
            int((x2 - x1) * scale_x),
            int((y2 - y1) * scale_y),
        )

    # —— 绘制 ——

    def paintEvent(self, event) -> None:
        if not self.pixmap():
            # 无图：显示占位文字（由 QLabel 绘制）
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._transform_deg or self._transform_flip:
            # 旋转/翻转预览：变换后的图片 + 水印跟随旋转
            self._paint_transformed_pixmap(painter, include_watermarks=True)
            painter.end()
            return
        # 常规：按当前缩放/平移绘制图片
        self._draw_base_image(painter)
        if self._crop_mode:
            self._paint_crop(painter)
        if self._crop_preview_rect is not None:
            self._paint_crop_preview(painter)
        else:
            self._paint_watermarks(painter)
        self._paint_image_watermark(painter)
        painter.end()

    def _draw_base_image(self, painter: QPainter) -> None:
        img_rect = self._image_draw_rect()
        pix = self.pixmap()
        if img_rect is None or pix is None or pix.isNull():
            return
        # 目标/源矩形须同为 QRectF（混用 QRect+QRectF 会无匹配重载而抛错）
        painter.drawPixmap(
            QRectF(img_rect), pix, QRectF(0, 0, pix.width(), pix.height())
        )

    def _paint_transformed_pixmap(
        self, painter: QPainter, include_watermarks: bool = False
    ) -> None:
        """旋转/翻转后的图片预览（所见即所得）。"""
        pix = self.pixmap()
        img_rect = self._image_draw_rect()
        if pix is None or img_rect is None:
            return
        painter.save()
        painter.translate(img_rect.center())
        if self._transform_flip == "horizontal":
            painter.scale(-1, 1)
        elif self._transform_flip == "vertical":
            painter.scale(1, -1)
        painter.rotate(-self._transform_deg)
        if self._transform_deg % 180 == 90:
            half_w, half_h = img_rect.height() / 2, img_rect.width() / 2
        else:
            half_w, half_h = img_rect.width() / 2, img_rect.height() / 2
        painter.drawPixmap(
            QRectF(-half_w, -half_h, half_w * 2, half_h * 2),
            pix,
            QRectF(0, 0, pix.width(), pix.height()),
        )
        if include_watermarks:
            # 水印在变换上下文中绘制（坐标相对图片中心），随图片一起旋转不消失
            self._paint_watermarks(painter, origin_offset=img_rect.center())
            self._paint_image_watermark(painter, origin_offset=img_rect.center())
        painter.restore()

    def _paint_crop_preview(self, painter: QPainter) -> None:
        """裁剪效果预览：选区内容放大显示（所见即所得）。"""
        pix = self.pixmap()
        img_rect = self._image_draw_rect()
        if pix is None or pix.isNull() or img_rect is None or self._crop_preview_rect is None:
            return
        label_rect = self._crop_preview_rect
        # Label 坐标 → 全分辨率 pixmap 坐标（按显示尺寸缩放）
        sx = pix.width() / max(1, img_rect.width())
        sy = pix.height() / max(1, img_rect.height())
        src = QRect(
            round((label_rect.x() - img_rect.x()) * sx),
            round((label_rect.y() - img_rect.y()) * sy),
            round(label_rect.width() * sx),
            round(label_rect.height() * sy),
        )
        src = src & QRect(0, 0, pix.width(), pix.height())
        if src.width() < 2 or src.height() < 2:
            return
        painter.drawPixmap(img_rect, pix, src)

    def _paint_image_watermark(
        self, painter: QPainter, origin_offset: QPoint | None = None
    ) -> None:
        """预览中真实渲染图片水印（右下角，随预览缩放）。"""
        pix = self._watermark_image
        if pix is None or pix.isNull():
            return
        img_rect = self._image_draw_rect()
        if img_rect is None:
            return
        ratio = img_rect.width() / max(1, self._orig_width)
        target_w = max(20, round(img_rect.width() * 0.25))
        target_h = max(20, round(pix.height() * target_w / max(1, pix.width())))
        scaled = pix.scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = img_rect.right() - scaled.width() - 8
        y = img_rect.bottom() - scaled.height() - 8
        if origin_offset is not None:
            x -= origin_offset.x()
            y -= origin_offset.y()
        painter.setOpacity(0.55)
        painter.drawPixmap(x, y, scaled)
        painter.setOpacity(1.0)

    def _paint_crop(self, painter: QPainter) -> None:
        img_rect = self._image_draw_rect()
        if img_rect is None:
            return
        rect = self._crop_rect
        if rect is None:
            # 无选区：提示绘制
            pen = QPen(QColor(57, 115, 219), 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(img_rect)
            return
        # 选区外遮罩（4 个半透明矩形）
        mask_color = QColor(57, 115, 219, 70)
        painter.setBrush(mask_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(0, 0, self.width(), rect.top())
        painter.drawRect(0, rect.bottom(), self.width(), self.height() - rect.bottom())
        painter.drawRect(0, rect.top(), rect.left(), rect.height())
        painter.drawRect(rect.right(), rect.top(), self.width() - rect.right(), rect.height())
        # 选区边框
        pen = QPen(QColor(57, 115, 219), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        # 四角手柄
        painter.setBrush(QColor(57, 115, 219))
        for corner in (rect.topLeft(), rect.topRight(),
                       rect.bottomLeft(), rect.bottomRight()):
            painter.fillRect(
                QRect(corner.x() - self._HANDLE_SIZE // 2,
                      corner.y() - self._HANDLE_SIZE // 2,
                      self._HANDLE_SIZE, self._HANDLE_SIZE),
                QColor(57, 115, 219),
            )

    def _paint_watermarks(
        self, painter: QPainter, origin_offset: QPoint | None = None
    ) -> None:
        from PySide6.QtGui import QFont, QColor as _QColor, QFontMetricsF

        for wm in self._items:
            rect = self._wm_rect(wm)
            if not rect:
                continue
            if origin_offset is not None:
                rect = rect.translated(
                    -origin_offset.x(), -origin_offset.y()
                )
            rotation = float(getattr(wm, "rotation", 0))
            painter.save()
            if rotation:
                # 水印框跟随文字旋转：框、文字、选中框在同一旋转上下文绘制
                painter.translate(rect.center())
                painter.rotate(-rotation)
            draw_rect = (
                QRect(-rect.width() // 2, -rect.height() // 2,
                      rect.width(), rect.height())
                if rotation
                else rect
            )
            selected = (wm.id == self._selected_id)
            pen = QPen(QColor(255, 255, 255), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(draw_rect)
            if wm.text.strip():
                img_rect2 = self._image_draw_rect()
                view_ratio = (
                    img_rect2.width() / max(1, self._orig_width)
                    if img_rect2 else 1.0
                )
                font_size = max(4.0, wm.font_size * view_ratio * max(0.1, wm.scale))
                font = QFont(wm.font_family)
                font.setPixelSize(round(font_size))
                metrics = QFontMetricsF(font)
                available_w = max(1.0, rect.width() - 4)
                available_h = max(1.0, rect.height() - 4)
                text_w = metrics.horizontalAdvance(wm.text)
                text_h = metrics.height()
                if text_w > available_w or text_h > available_h:
                    fit = min(
                        available_w / max(1.0, text_w),
                        available_h / max(1.0, text_h),
                    )
                    font.setPixelSize(max(1, round(font.pixelSize() * fit)))
                painter.setFont(font)
                wm_color = _QColor(wm.color)
                wm_color.setAlphaF(max(0.1, min(1.0, wm.opacity)))
                painter.setPen(wm_color)
                painter.drawText(
                    draw_rect, Qt.AlignmentFlag.AlignCenter, wm.text
                )
            if selected:
                pen = QPen(QColor(57, 115, 219), 2)
                painter.setPen(pen)
                painter.drawRect(draw_rect)
                for corner in (draw_rect.topLeft(), draw_rect.topRight(),
                               draw_rect.bottomLeft(), draw_rect.bottomRight()):
                    painter.fillRect(
                        QRect(corner.x() - self._HANDLE_SIZE // 2,
                              corner.y() - self._HANDLE_SIZE // 2,
                              self._HANDLE_SIZE, self._HANDLE_SIZE),
                        QColor(57, 115, 219),
                    )
            painter.restore()

    # —— 几何 ——

    def sizeHint(self) -> QSize:
        # 与图片尺寸解耦：预览区由布局伸缩填充，避免全分辨率 pixmap 撑爆窗口
        return QSize(320, 240)

    def minimumSizeHint(self) -> QSize:
        return QSize(80, 80)

    def _image_draw_rect(self) -> QRect | None:
        """图片在 Label 中的实际绘制区域（适配尺寸 × 缩放 + 平移）。"""
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return None
        fw, fh = self._fit_size()
        if fw <= 0 or fh <= 0:
            return None
        dw = max(1, round(fw * self._zoom))
        dh = max(1, round(fh * self._zoom))
        cr = self.contentsRect()
        x = cr.x() + (cr.width() - dw) // 2 + self._pan.x()
        y = cr.y() + (cr.height() - dh) // 2 + self._pan.y()
        return QRect(x, y, dw, dh)

    def _wm_rect(self, wm: WatermarkItem) -> QRect | None:
        img_rect = self._image_draw_rect()
        if not img_rect or not wm.text.strip():
            return None
        scale = max(0.1, wm.scale)
        view_ratio = img_rect.width() / max(1, self._orig_width)
        font_size = max(1, wm.font_size)
        text_len = max(1, len(wm.text))
        base_w = max(80.0, min(self._orig_width * 0.5, text_len * font_size)) * scale * view_ratio
        base_h = max(30.0, font_size * 1.6) * scale * view_ratio
        if wm.custom_x is not None and wm.custom_y is not None:
            cx = img_rect.x() + wm.custom_x * img_rect.width()
            cy = img_rect.y() + wm.custom_y * img_rect.height()
        else:
            rx, ry = _POSITION_RATIOS.get(wm.position, (0.85, 0.85))
            cx = img_rect.x() + rx * img_rect.width()
            cy = img_rect.y() + ry * img_rect.height()
        return QRect(
            int(cx - base_w / 2), int(cy - base_h / 2),
            int(base_w), int(base_h),
        )

    def _hit_watermark(self, pos: QPoint) -> str | None:
        for wm in reversed(self._items):
            rect = self._wm_rect(wm)
            if rect and self._rect_hit_test(rect, float(getattr(wm, "rotation", 0)), pos):
                return wm.id
        return None

    @staticmethod
    def _rect_hit_test(rect: QRect, rotation: float, pos: QPoint) -> bool:
        if not rotation:
            return rect.adjusted(-4, -4, 4, 4).contains(pos)
        import math

        center = rect.center()
        angle = math.radians(rotation)
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        rx = dx * math.cos(angle) - dy * math.sin(angle)
        ry = dx * math.sin(angle) + dy * math.cos(angle)
        return rect.adjusted(-4, -4, 4, 4).contains(
            QPoint(int(center.x() + rx), int(center.y() + ry))
        )

    def _hit_handle(self, pos: QPoint) -> bool:
        wm = self._get_item(self._selected_id)
        if wm is None:
            return False
        rect = self._wm_rect(wm)
        if not rect:
            return False
        hit_pos = pos
        rotation = float(getattr(wm, "rotation", 0))
        if rotation:
            import math

            center = rect.center()
            angle = math.radians(rotation)
            dx = pos.x() - center.x()
            dy = pos.y() - center.y()
            hit_pos = QPoint(
                int(center.x() + dx * math.cos(angle) - dy * math.sin(angle)),
                int(center.y() + dx * math.sin(angle) + dy * math.cos(angle)),
            )
        for corner in (rect.topLeft(), rect.topRight(),
                       rect.bottomLeft(), rect.bottomRight()):
            if (abs(hit_pos.x() - corner.x()) <= self._HANDLE_SIZE
                    and abs(hit_pos.y() - corner.y()) <= self._HANDLE_SIZE):
                return True
        return False

    def _get_item(self, wm_id: str | None) -> WatermarkItem | None:
        for wm in self._items:
            if wm.id == wm_id:
                return wm
        return None

    def _get_custom(self, wm_id: str) -> tuple[float, float]:
        wm = self._get_item(wm_id)
        img_rect = self._image_draw_rect()
        if wm is None or img_rect is None or img_rect.width() <= 0:
            return 0.5, 0.5
        rect = self._wm_rect(wm)
        if rect is None:
            return 0.5, 0.5
        cx = (rect.center().x() - img_rect.x()) / img_rect.width()
        cy = (rect.center().y() - img_rect.y()) / img_rect.height()
        return max(0.0, min(1.0, cx)), max(0.0, min(1.0, cy))

    def _move_selected(self, dx: int, dy: int) -> None:
        wm = self._get_item(self._wm_drag_item)
        img_rect = self._image_draw_rect()
        if wm is None or self._wm_orig_custom is None or img_rect is None:
            return
        if img_rect.width() <= 0 or img_rect.height() <= 0:
            return
        ox, oy = self._wm_orig_custom
        nx = max(0.0, min(1.0, ox + dx / img_rect.width()))
        ny = max(0.0, min(1.0, oy + dy / img_rect.height()))
        wm.custom_x = nx
        wm.custom_y = ny
        self.watermark_moved.emit(wm.id, nx, ny)
        self.update()

    def _scale_selected(self, dx: int) -> None:
        wm = self._get_item(self._wm_drag_item)
        img_rect = self._image_draw_rect()
        if wm is None or img_rect is None:
            return
        delta = dx / max(1, img_rect.width())
        wm.scale = max(0.1, min(5.0, wm.scale + delta * 1.5))
        self.watermark_scaled.emit(wm.id, wm.scale)
        self.update()


_POSITION_RATIOS: dict[str, tuple[float, float]] = {
    "top_left": (0.15, 0.15),
    "top_center": (0.5, 0.15),
    "top_right": (0.85, 0.15),
    "middle_left": (0.15, 0.5),
    "center": (0.5, 0.5),
    "middle_right": (0.85, 0.5),
    "bottom_left": (0.15, 0.85),
    "bottom_center": (0.5, 0.85),
    "bottom_right": (0.85, 0.85),
}
