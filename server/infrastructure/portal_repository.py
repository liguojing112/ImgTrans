from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column

from server.domain.portal import PortalModule
from server.infrastructure.database import Base, Database


class PortalModuleRecord(Base):
    __tablename__ = "portal_modules"

    module_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    image_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    link_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SqlAlchemyPortalRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, module_key: str) -> PortalModule | None:
        with self._database.session() as session:
            record = session.get(PortalModuleRecord, module_key)
            return _to_domain(record) if record is not None else None

    def list_enabled(self) -> tuple[PortalModule, ...]:
        with self._database.session() as session:
            records = session.scalars(
                select(PortalModuleRecord)
                .where(PortalModuleRecord.enabled.is_(True))
                .order_by(PortalModuleRecord.module_key)
            )
            return tuple(_to_domain(record) for record in records)

    def upsert(self, module: PortalModule) -> PortalModule:
        with self._database.session() as session:
            record = session.get(PortalModuleRecord, module.module_key)
            if record is None:
                record = PortalModuleRecord(module_key=module.module_key)
                session.add(record)
            record.title = module.title.strip()
            record.description = module.description.strip()
            record.image_url = module.image_url.strip()
            record.link_url = module.link_url.strip()
            record.enabled = module.enabled
            record.updated_at = datetime.now(timezone.utc)
            session.flush()
            return _to_domain(record)


def _to_domain(record: PortalModuleRecord) -> PortalModule:
    return PortalModule(
        module_key=record.module_key,
        title=record.title,
        description=record.description,
        image_url=record.image_url,
        link_url=record.link_url,
        enabled=record.enabled,
    )
