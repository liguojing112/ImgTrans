"""管理后台用户持久化 — SQLAlchemy 实现。"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Integer, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from server.domain.admin_users import (
    AdminUser,
    AdminUserConflict,
    format_permissions,
    parse_permissions,
)
from server.infrastructure.database import Base, Database


class AdminUserRecord(Base):
    __tablename__ = "admin_users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    permissions: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlAlchemyAdminUserRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def find_by_username(self, username: str) -> AdminUser | None:
        with self._database.session() as session:
            record = session.scalar(
                select(AdminUserRecord).where(AdminUserRecord.username == username)
            )
            return _to_user(record) if record is not None else None

    def get(self, user_id: int) -> AdminUser | None:
        with self._database.session() as session:
            record = session.get(AdminUserRecord, user_id)
            return _to_user(record) if record is not None else None

    def create(self, user: AdminUser) -> AdminUser:
        record = AdminUserRecord(
            username=user.username,
            password_hash=user.password_hash,
            role=user.role,
            permissions=format_permissions(user.permissions),
            enabled=user.enabled,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
        with self._database.session() as session:
            session.add(record)
            try:
                session.flush()
            except IntegrityError:
                raise AdminUserConflict(f"用户名已存在: {user.username}")
            return _to_user(record)

    def list_all(self) -> list[AdminUser]:
        with self._database.session() as session:
            records = session.scalars(
                select(AdminUserRecord).order_by(AdminUserRecord.user_id)
            ).all()
            return [_to_user(record) for record in records]

    def update_permissions(self, user_id: int, permissions: frozenset[str]) -> AdminUser:
        with self._database.session() as session:
            record = session.get(AdminUserRecord, user_id)
            if record is None:
                raise AdminUserConflict(f"用户不存在: {user_id}")
            record.permissions = format_permissions(permissions)
            return _to_user(record)

    def set_enabled(self, user_id: int, enabled: bool) -> AdminUser:
        with self._database.session() as session:
            record = session.get(AdminUserRecord, user_id)
            if record is None:
                raise AdminUserConflict(f"用户不存在: {user_id}")
            record.enabled = enabled
            return _to_user(record)

    def update_password(self, user_id: int, password_hash: str) -> AdminUser:
        with self._database.session() as session:
            record = session.get(AdminUserRecord, user_id)
            if record is None:
                raise AdminUserConflict(f"用户不存在: {user_id}")
            record.password_hash = password_hash
            return _to_user(record)

    def record_login(self, user_id: int) -> None:
        with self._database.session() as session:
            record = session.get(AdminUserRecord, user_id)
            if record is not None:
                record.last_login_at = datetime.now(timezone.utc)

    def count_super(self) -> int:
        with self._database.session() as session:
            return len(
                session.scalars(
                    select(AdminUserRecord).where(AdminUserRecord.role == "super")
                ).all()
            )


def _to_user(record: AdminUserRecord) -> AdminUser:
    return AdminUser(
        user_id=record.user_id,
        username=record.username,
        password_hash=record.password_hash,
        role=record.role,
        permissions=parse_permissions(record.permissions),
        enabled=record.enabled,
        created_at=record.created_at,
        last_login_at=record.last_login_at,
    )
