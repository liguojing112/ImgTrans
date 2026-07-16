from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from server.domain.audit import AuditEvent


class AuditRepository(Protocol):
    def record(
        self,
        actor: str,
        action: str,
        resource: str,
        correlation_id: str,
        status_code: int,
        occurred_at: datetime,
    ) -> AuditEvent: ...

    def list_recent(self, limit: int) -> tuple[AuditEvent, ...]: ...


class AuditManagementAction:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    def record(
        self,
        actor: str,
        action: str,
        resource: str,
        correlation_id: str,
        status_code: int,
    ) -> AuditEvent:
        return self._repository.record(
            actor,
            action,
            resource,
            correlation_id,
            status_code,
            datetime.now(timezone.utc),
        )

    def list_recent(self, limit: int = 200) -> tuple[AuditEvent, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("Audit list limit is invalid")
        return self._repository.list_recent(limit)

