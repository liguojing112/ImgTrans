from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from server.domain.models import (
    ModelRelease,
    ModelReleaseConflict,
    ModelReleaseNotFound,
    ModelReleaseSpec,
    ModelReleaseStatus,
)
from server.infrastructure.database import Base, Database


class ModelReleaseRecord(Base):
    __tablename__ = "model_releases"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_model_release_size"),
        CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn')",
            name="ck_model_release_status",
        ),
        UniqueConstraint(
            "model_id", "version", "platform", "architecture",
            name="uq_model_release_target_version",
        ),
        Index("ix_model_release_manifest", "platform", "architecture", "status"),
    )

    release_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    architecture: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    object_version: Mapped[str] = mapped_column(String(256), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SqlAlchemyModelReleaseRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, spec: ModelReleaseSpec) -> ModelRelease:
        record = ModelReleaseRecord(
            **{name: getattr(spec, name) for name in spec.__dataclass_fields__},
            status=ModelReleaseStatus.DRAFT.value,
            created_at=_utc_now(),
        )
        try:
            with self._database.session() as session:
                session.add(record)
                session.flush()
                return _to_domain(record)
        except IntegrityError as error:
            raise ModelReleaseConflict("Model release already exists") from error

    def publish(self, release_id: int) -> ModelRelease:
        with self._database.session() as session:
            record = _get_locked(session, release_id)
            if record.status != ModelReleaseStatus.DRAFT.value:
                raise ModelReleaseConflict("Only draft model releases can be published")
            record.status = ModelReleaseStatus.PUBLISHED.value
            record.published_at = _utc_now()
            session.flush()
            return _to_domain(record)

    def withdraw(self, release_id: int) -> ModelRelease:
        with self._database.session() as session:
            record = _get_locked(session, release_id)
            if record.status != ModelReleaseStatus.PUBLISHED.value:
                raise ModelReleaseConflict("Only published model releases can be withdrawn")
            record.status = ModelReleaseStatus.WITHDRAWN.value
            record.withdrawn_at = _utc_now()
            session.flush()
            return _to_domain(record)

    def list_all(self) -> tuple[ModelRelease, ...]:
        with self._database.session() as session:
            records = session.scalars(
                select(ModelReleaseRecord).order_by(ModelReleaseRecord.release_id.desc())
            )
            return tuple(_to_domain(record) for record in records)

    def list_published(
        self, platform: str, architecture: str
    ) -> tuple[ModelRelease, ...]:
        with self._database.session() as session:
            records = session.scalars(
                select(ModelReleaseRecord)
                .where(
                    ModelReleaseRecord.platform == platform,
                    ModelReleaseRecord.architecture == architecture,
                    ModelReleaseRecord.status == ModelReleaseStatus.PUBLISHED.value,
                )
                .order_by(ModelReleaseRecord.model_id, ModelReleaseRecord.release_id.desc())
            )
            newest: dict[str, ModelReleaseRecord] = {}
            for record in records:
                newest.setdefault(record.model_id, record)
            return tuple(_to_domain(record) for record in newest.values())


def _get_locked(session, release_id: int) -> ModelReleaseRecord:
    record = session.scalar(
        select(ModelReleaseRecord)
        .where(ModelReleaseRecord.release_id == release_id)
        .with_for_update()
    )
    if record is None:
        raise ModelReleaseNotFound("Model release was not found")
    return record


def _to_domain(record: ModelReleaseRecord) -> ModelRelease:
    return ModelRelease(
        release_id=record.release_id,
        spec=ModelReleaseSpec(
            model_id=record.model_id,
            version=record.version,
            platform=record.platform,
            architecture=record.architecture,
            filename=record.filename,
            object_key=record.object_key,
            object_version=record.object_version,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
        ),
        status=ModelReleaseStatus(record.status),
        created_at=record.created_at,
        published_at=record.published_at,
        withdrawn_at=record.withdrawn_at,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
