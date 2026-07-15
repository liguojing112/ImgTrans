from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if "--smoke-test" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

try:
    from .dependency_probe import collect_report, write_report
    from .window import BootstrapWindow
except ImportError:
    from dependency_probe import collect_report, write_report
    from window import BootstrapWindow


def create_application(argv: list[str] | None = None) -> QApplication:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv or sys.argv)
    app.setApplicationName("Image Translator Platform Bootstrap")
    app.setOrganizationName("ImgTrans")
    return app


def run_smoke_test(*, report_path: Path | None = None) -> int:
    app = create_application([sys.argv[0]])
    window = BootstrapWindow(default_duration_ms=200)
    window.show()
    window.start_probe(200)

    result = {"outcome": "timeout"}

    def finish_shutdown() -> None:
        if window.is_probe_running:
            QTimer.singleShot(10, finish_shutdown)
            return
        window.close()
        app.quit()

    def complete(outcome: str) -> None:
        result["outcome"] = outcome
        QTimer.singleShot(0, finish_shutdown)

    window.probe_completed.connect(complete)
    QTimer.singleShot(2_000, lambda: result["outcome"] == "timeout" and complete("timeout"))
    app.exec()

    report = collect_report(import_modules=True)
    report["smoke_test"] = {
        "outcome": result["outcome"],
        "window_created": True,
        "worker_completed": result["outcome"] == "finished",
    }
    if report_path is not None:
        write_report(report, report_path)
    return 0 if result["outcome"] == "finished" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PySide6 platform bootstrap prototype")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--duration-ms", type=int, default=3_000)
    args = parser.parse_args(argv)

    if args.smoke_test:
        return run_smoke_test(report_path=args.report)

    app = create_application()
    window = BootstrapWindow(default_duration_ms=args.duration_ms)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
