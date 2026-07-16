from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: int
    actor: str
    action: str
    resource: str
    correlation_id: str
    occurred_at: datetime
    status_code: int

