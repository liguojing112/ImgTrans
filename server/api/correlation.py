from __future__ import annotations

import re
from uuid import uuid4


CORRELATION_HEADER = "X-Correlation-ID"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def normalize_correlation_id(value: str | None) -> str:
    if value is not None and _VALID_CORRELATION_ID.fullmatch(value):
        return value
    return uuid4().hex
