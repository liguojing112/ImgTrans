"""商品图片上传 — 外部文件拖入应被接收。

覆盖历史缺陷：缩略图 QListWidget 处于 InternalMove 模式时，外部文件拖到
列表区会被列表吞掉（只认自身条目重排），导致「拖图片进预览区」无反应。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QPoint, QMimeData
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from src.ui.product.widgets.image_uploader import ImageUploader


def _app() -> QApplication:
    return QApplication.instance() or QApplication(["image-uploader-drop-test"])


def _drop_on(widget, path: Path) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)


def test_drop_over_list_receives_file(tmp_path: Path) -> None:
    """拖到缩略图列表区（占满面板的主体区域）应把图片加入 uploader。"""
    _app()
    uploader = ImageUploader()
    png = tmp_path / "a.png"
    png.write_bytes(b"png-bytes")
    _drop_on(uploader._list, png)
    images = uploader.images()
    assert len(images) == 1
    assert images[0].path == png


def test_drop_over_list_ignores_unsupported(tmp_path: Path) -> None:
    _app()
    uploader = ImageUploader()
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"gif-bytes")
    _drop_on(uploader._list, gif)
    assert uploader.images() == []


def test_drop_over_frame_receives_file(tmp_path: Path) -> None:
    """拖到按钮行/空白区（frame 本身）也应接收。"""
    _app()
    uploader = ImageUploader()
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpg-bytes")
    _drop_on(uploader, jpg)
    assert len(uploader.images()) == 1
