from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from server.domain.audit import AuditEvent
from server.infrastructure.database import Base, Database


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    resource: Mapped[str] = mapped_column(String(500), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)


class SqlAlchemyAuditRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def record(
        self,
        actor: str,
        action: str,
        resource: str,
        correlation_id: str,
        status_code: int,
        occurred_at: datetime,
    ) -> AuditEvent:
        with self._database.session() as session:
            record = AuditEventRecord(
                actor=actor[:100],
                action=action[:20],
                resource=resource[:500],
                correlation_id=correlation_id[:64],
                occurred_at=occurred_at,
                status_code=status_code,
            )
            session.add(record)
            session.flush()
            return _to_domain(record)

    def list_recent(self, limit: int) -> tuple[AuditEvent, ...]:
        with self._database.session() as session:
            records = session.scalars(
                select(AuditEventRecord)
                .order_by(AuditEventRecord.event_id.desc())
                .limit(limit)
            )
            return tuple(_to_domain(record) for record in records)


def _to_domain(record: AuditEventRecord) -> AuditEvent:
    occurred_at = record.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return AuditEvent(
        event_id=record.event_id,
        actor=record.actor,
        action=record.action,
        resource=record.resource,
        correlation_id=record.correlation_id,
        occurred_at=occurred_at,
        status_code=record.status_code,
    )

