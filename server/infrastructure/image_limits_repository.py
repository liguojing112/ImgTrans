from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from server.domain.image_limits import (
    ImageLimitConflict,
    ImageLimitNotFound,
    ImageLimitStatus,
    ImageLimitValues,
    ImageLimitVersion,
)
from server.infrastructure.database import Base, Database


class ImageLimitVersionRecord(Base):
    __tablename__ = "image_limit_versions"
    __table_args__ = (
        CheckConstraint("min_width > 0", name="ck_image_limits_min_width"),
        CheckConstraint("min_height > 0", name="ck_image_limits_min_height"),
        CheckConstraint("max_width >= min_width", name="ck_image_limits_widths"),
        CheckConstraint("max_height >= min_height", name="ck_image_limits_heights"),
        CheckConstraint("max_bytes > 0", name="ck_image_limits_max_bytes"),
        CheckConstraint(
            "status IN ('draft', 'published', 'superseded')",
            name="ck_image_limits_status",
        ),
        Index(
            "uq_image_limits_single_published",
            "status",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    min_width: Mapped[int] = mapped_column(Integer, nullable=False)
    min_height: Mapped[int] = mapped_column(Integer, nullable=False)
    max_width: Mapped[int] = mapped_column(Integer, nullable=False)
    max_height: Mapped[int] = mapped_column(Integer, nullable=False)
    max_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SqlAlchemyImageLimitRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create_draft(self, values: ImageLimitValues) -> ImageLimitVersion:
        with self._database.session() as session:
            record = _new_record(values)
            session.add(record)
            session.flush()
            return _to_domain(record)

    def update_draft(
        self, version: int, values: ImageLimitValues
    ) -> ImageLimitVersion:
        with self._database.session() as session:
            record = session.get(ImageLimitVersionRecord, version)
            if record is None:
                raise ImageLimitNotFound("Image limit version was not found")
            if record.status != ImageLimitStatus.DRAFT.value:
                raise ImageLimitConflict("Only draft versions can be edited")
            _apply_values(record, values)
            session.flush()
            return _to_domain(record)

    def publish(self, version: int) -> ImageLimitVersion:
        try:
            with self._database.session() as session:
                record = session.scalar(
                    select(ImageLimitVersionRecord)
                    .where(ImageLimitVersionRecord.version == version)
                    .with_for_update()
                )
                if record is None:
                    raise ImageLimitNotFound("Image limit version was not found")
                if record.status != ImageLimitStatus.DRAFT.value:
                    raise ImageLimitConflict("Only draft versions can be published")
                self._supersede_current(session)
                now = _utc_now()
                record.status = ImageLimitStatus.PUBLISHED.value
                record.published_at = now
                session.flush()
                return _to_domain(record)
        except IntegrityError as error:
            raise ImageLimitConflict("Another configuration was published") from error

    def rollback(self, source_version: int) -> ImageLimitVersion:
        try:
            with self._database.session() as session:
                source = session.scalar(
                    select(ImageLimitVersionRecord)
                    .where(ImageLimitVersionRecord.version == source_version)
                    .with_for_update()
                )
                if source is None:
                    raise ImageLimitNotFound("Image limit version was not found")
                if source.status == ImageLimitStatus.DRAFT.value:
                    raise ImageLimitConflict("Cannot roll back to a draft version")
                self._supersede_current(session)
                record = _new_record(
                    _record_values(source),
                    source_version=source.version,
                )
                session.add(record)
                session.flush()
                record.status = ImageLimitStatus.PUBLISHED.value
                record.published_at = _utc_now()
                session.flush()
                return _to_domain(record)
        except IntegrityError as error:
            raise ImageLimitConflict("Another configuration was published") from error

    def get_published(self) -> ImageLimitVersion | None:
        with self._database.session() as session:
            record = session.scalar(
                select(ImageLimitVersionRecord).where(
                    ImageLimitVersionRecord.status
                    == ImageLimitStatus.PUBLISHED.value
                )
            )
            return _to_domain(record) if record is not None else None

    def list_versions(self) -> tuple[ImageLimitVersion, ...]:
        with self._database.session() as session:
            records = session.scalars(
                select(ImageLimitVersionRecord).order_by(
                    ImageLimitVersionRecord.version.desc()
                )
            )
            return tuple(_to_domain(record) for record in records)

    @staticmethod
    def _supersede_current(session) -> None:
        current = session.scalar(
            select(ImageLimitVersionRecord)
            .where(
                ImageLimitVersionRecord.status == ImageLimitStatus.PUBLISHED.value
            )
            .with_for_update()
        )
        if current is not None:
            current.status = ImageLimitStatus.SUPERSEDED.value


def _new_record(
    values: ImageLimitValues,
    *,
    source_version: int | None = None,
) -> ImageLimitVersionRecord:
    return ImageLimitVersionRecord(
        min_width=values.min_width,
        min_height=values.min_height,
        max_width=values.max_width,
        max_height=values.max_height,
        max_bytes=values.max_bytes,
        status=ImageLimitStatus.DRAFT.value,
        created_at=_utc_now(),
        source_version=source_version,
    )


def _apply_values(record: ImageLimitVersionRecord, values: ImageLimitValues) -> None:
    record.min_width = values.min_width
    record.min_height = values.min_height
    record.max_width = values.max_width
    record.max_height = values.max_height
    record.max_bytes = values.max_bytes


def _record_values(record: ImageLimitVersionRecord) -> ImageLimitValues:
    return ImageLimitValues(
        min_width=record.min_width,
        min_height=record.min_height,
        max_width=record.max_width,
        max_height=record.max_height,
        max_bytes=record.max_bytes,
    )


def _to_domain(record: ImageLimitVersionRecord) -> ImageLimitVersion:
    return ImageLimitVersion(
        version=record.version,
        values=_record_values(record),
        status=ImageLimitStatus(record.status),
        created_at=record.created_at,
        published_at=record.published_at,
        source_version=record.source_version,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
