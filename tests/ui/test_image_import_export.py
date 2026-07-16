import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from src.application.bootstrap import StartupSnapshot
from src.application.image_io import ExportImage, ImportImage
from src.domain.image import ImageLimits
from src.domain.product import ProductInfo
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.ui.main_window import MainWindow


class ImmediateTaskRunner:
    def submit(self, operation: Any, on_success: Any, on_error: Any) -> None:
        try:
            on_success(operation())
        except Exception as error:
            on_error(error)


def test_window_imports_displays_and_exports_real_image(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication(["imgtrans-image-test"])
    source = tmp_path / "product.png"
    Image.new("RGBA", (120, 80), (10, 80, 160, 180)).save(source)
    codec = PillowImageCodec()
    window = MainWindow(
        StartupSnapshot(
            ProductInfo("图片翻译", "0.1.0", "M1"),
            tmp_path / "data",
            tmp_path / "cache",
        ),
        ImportImage(codec, ImageLimits()),
        ExportImage(codec),
        ImmediateTaskRunner(),
    )
    window.show()
    window.request_import(source)
    application.processEvents()
    assert window.current_document is not None
    assert window.current_document.asset.source_path == source.resolve()
    assert window.content_stack.currentWidget() is window.image_workspace
    assert window.image_canvas.pixmap() is not None
    assert window.export_button.isEnabled()
    assert "120×80" in window.readiness_label.text()

    target = tmp_path / "export.png"
    window.request_export(target)
    application.processEvents()
    assert target.is_file()
    assert window.statusBar().currentMessage() == "已导出：export.png"
    window.close()
