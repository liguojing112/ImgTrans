from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("imgtrans")
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
        _attach_file_handler(logger)
    return logger


def _attach_file_handler(logger: logging.Logger) -> None:
    """把日志同时写入 data_dir/logs/imgtrans.log，便于离线排障。"""
    try:
        from src.platform.paths import PlatformPaths

        log_dir = PlatformPaths.discover().data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "imgtrans.log", encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError:
        pass
