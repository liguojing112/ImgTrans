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
    return logger
