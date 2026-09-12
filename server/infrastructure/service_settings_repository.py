"""第三方服务配置持久化 — SQLAlchemy 实现。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from server.infrastructure.database import Base, Database


@dataclass(frozen=True, slots=True)
class ServiceSettingsRow:
    wechat_appid: str | None = None
    wechat_mchid: str | None = None
    wechat_apiv3_key_cipher: str | None = None
    wechat_private_key_cipher: str | None = None
    wechat_serial_no: str | None = None
    wechat_platform_cert_cipher: str | None = None
    wechat_public_key_id: str | None = None
    wechat_notify_url: str | None = None
    glm_api_key_cipher: str | None = None
    glm_model: str | None = None
    glm_base_url: str | None = None


class ServiceSettingsRecord(Base):
    __tablename__ = "service_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wechat_appid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wechat_mchid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wechat_apiv3_key_cipher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    wechat_private_key_cipher: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    wechat_serial_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wechat_platform_cert_cipher: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    wechat_public_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wechat_notify_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    glm_api_key_cipher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    glm_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    glm_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlAlchemyServiceSettingsRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def load(self) -> ServiceSettingsRow | None:
        with self._database.session() as session:
            record = session.get(ServiceSettingsRecord, 1)
            return _to_row(record) if record is not None else None

    def save(self, row: ServiceSettingsRow) -> None:
        with self._database.session() as session:
            record = session.get(ServiceSettingsRecord, 1)
            if record is None:
                record = ServiceSettingsRecord(id=1)
                session.add(record)
            record.wechat_appid = row.wechat_appid
            record.wechat_mchid = row.wechat_mchid
            record.wechat_apiv3_key_cipher = row.wechat_apiv3_key_cipher
            record.wechat_private_key_cipher = row.wechat_private_key_cipher
            record.wechat_serial_no = row.wechat_serial_no
            record.wechat_platform_cert_cipher = row.wechat_platform_cert_cipher
            record.wechat_public_key_id = row.wechat_public_key_id
            record.wechat_notify_url = row.wechat_notify_url
            record.glm_api_key_cipher = row.glm_api_key_cipher
            record.glm_model = row.glm_model
            record.glm_base_url = row.glm_base_url
            record.updated_at = _utc_now()


def _to_row(record: ServiceSettingsRecord) -> ServiceSettingsRow:
    return ServiceSettingsRow(
        wechat_appid=record.wechat_appid,
        wechat_mchid=record.wechat_mchid,
        wechat_apiv3_key_cipher=record.wechat_apiv3_key_cipher,
        wechat_private_key_cipher=record.wechat_private_key_cipher,
        wechat_serial_no=record.wechat_serial_no,
        wechat_platform_cert_cipher=record.wechat_platform_cert_cipher,
        wechat_public_key_id=record.wechat_public_key_id,
        wechat_notify_url=record.wechat_notify_url,
        glm_api_key_cipher=record.glm_api_key_cipher,
        glm_model=record.glm_model,
        glm_base_url=record.glm_base_url,
    )


def _utc_now() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)
