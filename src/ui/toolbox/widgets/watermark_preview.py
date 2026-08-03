"""交互式图片预览 — 截图工具式裁剪 + 水印框（选中/移动/缩放）。

裁剪模式（截图工具交互）：
- 点击"裁剪"进入模式；按下拖动绘制蓝色半透明遮罩选区
- 选区四角小方块可拖拽调整；选区整体可拖拽移动
- 双击选区确认裁剪；Esc 或"取消"退出模式
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPen, QColor
from PySide6.QtWidgets import QLabel

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
        # 裁剪模式
        self._crop_mode = False
        self._crop_rect: QRect | None = None  # 选区（Label 坐标）
        self._crop_drag: str | None = None  # "draw" / "move" / "tl" "tr" "bl" "br"
        self._crop_drag_start: QPoint | None = None
        self._crop_orig_rect: QRect | None = None
        # 水印拖拽
        self._wm_drag: str | None = None  # "move" / "scale"
        self._wm_drag_start: QPoint | None = None
        self._wm_drag_item: str | None = None
        self._wm_orig_custom: tuple[float, float] | None = None

    # —— 数据 ——

    def set_items(self, items: list[WatermarkItem]) -> None:
        self._items = list(items)
        self.update()

    def set_original_size(self, w: int, h: int) -> None:
        self._orig_width = max(1, w)
        self._orig_height = max(1, h)

    def set_selected(self, wm_id: str | None) -> None:
        self._selected_id = wm_id
        self.update()

    # —— 裁剪模式 ——

    def set_crop_mode(self, active: bool) -> None:
        """进入/退出裁剪模式。"""
        self._crop_mode = active
        if not active:
            self._crop_rect = None
            self._crop_drag = None
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

    # —— 鼠标事件 ——

    def mousePressEvent(self, event: QMouseEvent) -> None:
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
            return
        wm_id = self._hit_watermark(pos)
        if wm_id:
            self._selected_id = wm_id
            self.watermark_selected.emit(wm_id)
            self._wm_drag = "move"
            self._wm_drag_item = wm_id
            self._wm_drag_start = pos
            self._wm_orig_custom = self._get_custom(wm_id)
            self.update()
            return
        self._selected_id = None
        self.watermark_selected.emit("")
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.pixmap():
            return
        pos = event.pos()
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
        elif self._crop_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.pixmap():
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # 裁剪拖拽结束 → 同步选区到参数（不退出模式）
        if self._crop_mode and self._crop_rect is not None and self._crop_drag:
            rect = self._crop_to_image(self._crop_rect)
            if rect:
                self.crop_box_changed.emit(rect.x(), rect.y(),
                                           rect.width(), rect.height())
        self._crop_drag = None
        self._crop_drag_start = None
        self._crop_orig_rect = None
        self._wm_drag = None
        self._wm_drag_item = None
        self._wm_drag_start = None
        self._wm_orig_custom = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """双击选区 → 确认裁剪。"""
        if not self._crop_mode or not self._crop_rect:
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
        super().paintEvent(event)
        painter = QPainter(self)
        if self._crop_mode:
            self._paint_crop(painter)
        self._paint_watermarks(painter)
        painter.end()

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

    def _paint_watermarks(self, painter: QPainter) -> None:
        for wm in self._items:
            rect = self._wm_rect(wm)
            if not rect:
                continue
            selected = (wm.id == self._selected_id)
            pen = QPen(QColor(255, 255, 255), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            if wm.text.strip():
                from PySide6.QtGui import QFont, QColor as _QColor, QFontMetricsF
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
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, wm.text)
            if selected:
                pen = QPen(QColor(57, 115, 219), 2)
                painter.setPen(pen)
                painter.drawRect(rect)
                for corner in (rect.topLeft(), rect.topRight(),
                               rect.bottomLeft(), rect.bottomRight()):
                    painter.fillRect(
                        QRect(corner.x() - self._HANDLE_SIZE // 2,
                              corner.y() - self._HANDLE_SIZE // 2,
                              self._HANDLE_SIZE, self._HANDLE_SIZE),
                        QColor(57, 115, 219),
                    )

    # —— 几何 ——

    def _image_draw_rect(self) -> QRect | None:
        """图片在 Label 中的实际绘制区域（考虑对齐方式）。"""
        pix = self.pixmap()
        if not pix:
            return None
        cr = self.contentsRect()
        area_w = cr.width()
        area_h = cr.height()
        pix_w = pix.width()
        pix_h = pix.height()
        if pix_w <= 0 or pix_h <= 0:
            return None
        draw_w = pix_w
        draw_h = pix_h
        alignment = self.alignment()
        x = cr.x()
        y = cr.y()
        if alignment & Qt.AlignmentFlag.AlignHCenter:
            x = cr.x() + (area_w - draw_w) // 2
        elif alignment & Qt.AlignmentFlag.AlignRight:
            x = cr.x() + (area_w - draw_w)
        if alignment & Qt.AlignmentFlag.AlignVCenter:
            y = cr.y() + (area_h - draw_h) // 2
        elif alignment & Qt.AlignmentFlag.AlignBottom:
            y = cr.y() + (area_h - draw_h)
        return QRect(x, y, draw_w, draw_h)

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
            if rect and rect.adjusted(-4, -4, 4, 4).contains(pos):
                return wm.id
        return None

    def _hit_handle(self, pos: QPoint) -> bool:
        wm = self._get_item(self._selected_id)
        if wm is None:
            return False
        rect = self._wm_rect(wm)
        if not rect:
            return False
        for corner in (rect.topLeft(), rect.topRight(),
                       rect.bottomLeft(), rect.bottomRight()):
            if (abs(pos.x() - corner.x()) <= self._HANDLE_SIZE
                    and abs(pos.y() - corner.y()) <= self._HANDLE_SIZE):
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
