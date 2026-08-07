from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("imgtrans")
    logger.setLevel(level)
    logger.propagate = False
    # 无论 logger 是否已被其他模块预置 handler，都确保有文件日志兜底
    if not any(
        isinstance(handler, logging.FileHandler) for handler in logger.handlers
    ):
        _attach_file_handler(logger)
    if not any(
        isinstance(handler, logging.StreamHandler) for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    return logger


def _attach_file_handler(logger: logging.Logger) -> None:
    """日志写入 data_dir/logs/imgtrans.log，失败则兜底写 exe 同级。"""
    try:
        from src.platform.paths import PlatformPaths

        log_dir = PlatformPaths.discover().data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _add_file_handler(logger, log_dir / "imgtrans.log")
    except OSError:
        pass
    try:
        import sys

        _add_file_handler(
            logger, Path(sys.executable).resolve().parent / "imgtrans-debug.log"
        )
    except OSError:
        pass


def _add_file_handler(logger: logging.Logger, path: Path) -> None:
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(file_handler)
