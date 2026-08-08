from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from server.domain.activation import (
    ActivationCode,
    ActivationConflict,
    ActivationDenied,
    ActivationNotFound,
    ActivationPlan,
    ActivationPlanValues,
    DeviceActivation,
    UsageRecord,
)
from server.infrastructure.database import Base, Database
from server.infrastructure.secrets_cipher import SecretsCipher


class ActivationPlanRecord(Base):
    __tablename__ = "activation_plans"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="ck_activation_plan_amount"),
        CheckConstraint(
            "duration_hours >= 0 AND duration_hours <= 87600",
            name="ck_activation_plan_duration",
        ),
    )

    plan_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    plan_type: Mapped[str] = mapped_column(String(10), nullable=False, default="duration")
    quota: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sale_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sale_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    benefits: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActivationCodeRecord(Base):
    __tablename__ = "activation_codes"
    __table_args__ = (
        CheckConstraint(
            "duration_hours >= 0 AND duration_hours <= 87600",
            name="ck_activation_code_duration",
        ),
        UniqueConstraint("code_digest", name="uq_activation_code_digest"),
        UniqueConstraint("token_digest", name="uq_activation_token_digest"),
    )

    code_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("activation_plans.plan_id"), nullable=False, index=True)
    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    device_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quota_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quota_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    code_plaintext_cipher: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )


class UsageRecordRecord(Base):
    __tablename__ = "usage_records"

    usage_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_id: Mapped[str] = mapped_column(
        ForeignKey("activation_codes.code_id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class SqlAlchemyActivationRepository:
    def __init__(
        self, database: Database, cipher: SecretsCipher | None = None
    ) -> None:
        self._database = database
        self._cipher = cipher
        self._activation_lock = Lock()

    def create_plan(self, values: ActivationPlanValues) -> ActivationPlan:
        now = _utc_now()
        with self._database.session() as session:
            record = ActivationPlanRecord(
                name=values.name.strip(),
                amount_minor=values.amount_minor,
                currency=values.currency,
                duration_hours=values.duration_hours,
                enabled=values.enabled,
                plan_type=values.plan_type,
                quota=values.quota,
                sale_amount_minor=values.sale_amount_minor,
                sale_ends_at=values.sale_ends_at,
                benefits=values.benefits or None,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.flush()
            return _plan_to_domain(record)

    def update_plan(
        self, plan_id: int, values: ActivationPlanValues
    ) -> ActivationPlan:
        with self._database.session() as session:
            record = session.get(ActivationPlanRecord, plan_id)
            if record is None:
                raise ActivationNotFound("Activation plan was not found")
            record.name = values.name.strip()
            record.amount_minor = values.amount_minor
            record.currency = values.currency
            record.duration_hours = values.duration_hours
            record.enabled = values.enabled
            record.plan_type = values.plan_type
            record.quota = values.quota
            record.sale_amount_minor = values.sale_amount_minor
            record.sale_ends_at = values.sale_ends_at
            record.benefits = values.benefits or None
            record.updated_at = _utc_now()
            session.flush()
            return _plan_to_domain(record)

    def delete_plan(self, plan_id: int) -> None:
        """删除方案，并级联删除该方案下的激活码及其用量记录。

        注意：会作废该方案下已发给客户的所有激活码（客户已激活的码失效）。
        """
        with self._database.session() as session:
            record = session.get(ActivationPlanRecord, plan_id)
            if record is None:
                raise ActivationNotFound("Activation plan was not found")
            code_ids = select(ActivationCodeRecord.code_id).where(
                ActivationCodeRecord.plan_id == plan_id
            )
            session.execute(
                delete(UsageRecordRecord).where(
                    UsageRecordRecord.code_id.in_(code_ids)
                )
            )
            session.execute(
                delete(ActivationCodeRecord).where(
                    ActivationCodeRecord.plan_id == plan_id
                )
            )
            session.delete(record)

    def list_plans(self) -> tuple[ActivationPlan, ...]:
        with self._database.session() as session:
            records = session.scalars(
                select(ActivationPlanRecord).order_by(ActivationPlanRecord.plan_id.desc())
            )
            return tuple(_plan_to_domain(record) for record in records)

    def get_plan(self, plan_id: int) -> ActivationPlan:
        with self._database.session() as session:
            record = session.get(ActivationPlanRecord, plan_id)
            if record is None:
                raise ActivationNotFound("Activation plan was not found")
            return _plan_to_domain(record)

    def create_codes(
        self,
        plan_id: int,
        duration_hours: int,
        quota_total: int,
        code_digests: tuple[str, ...],
        plaintexts: tuple[str, ...] = (),
    ) -> tuple[ActivationCode, ...]:
        try:
            with self._database.session() as session:
                plan = session.get(ActivationPlanRecord, plan_id)
                if plan is None:
                    raise ActivationNotFound("Activation plan was not found")
                if not plan.enabled:
                    raise ActivationConflict("Disabled activation plans cannot issue codes")
                now = _utc_now()
                plaintext_ciphers = (
                    tuple(self._cipher.encrypt(value) for value in plaintexts)
                    if self._cipher is not None and plaintexts
                    else (None,) * len(code_digests)
                )
                records = tuple(
                    ActivationCodeRecord(
                        code_id=str(uuid4()),
                        plan_id=plan_id,
                        duration_hours=duration_hours,
                        quota_total=quota_total,
                        quota_remaining=quota_total,
                        code_digest=digest,
                        code_plaintext_cipher=plaintext_cipher,
                        disabled=False,
                        created_at=now,
                    )
                    for digest, plaintext_cipher in zip(
                        code_digests, plaintext_ciphers, strict=True
                    )
                )
                session.add_all(records)
                session.flush()
                return tuple(
                    _code_to_domain(record, self._cipher) for record in records
                )
        except IntegrityError as error:
            raise ActivationConflict("Activation code collision") from error

    def list_codes(self, code_digest: str | None = None) -> tuple[ActivationCode, ...]:
        statement = select(ActivationCodeRecord).order_by(
            ActivationCodeRecord.created_at.desc()
        )
        if code_digest:
            statement = statement.where(
                ActivationCodeRecord.code_digest == code_digest
            )
        with self._database.session() as session:
            records = session.scalars(statement)
            return tuple(_code_to_domain(record, self._cipher) for record in records)

    def list_codes_page(
        self,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        code_digest: str | None = None,
    ) -> tuple[tuple[ActivationCode, ...], int]:
        """分页查询激活码，可按状态筛选、按摘要精确定位。返回 (激活码, 总数)。"""
        statement = select(ActivationCodeRecord)
        if status == "bound":
            statement = statement.where(
                ActivationCodeRecord.device_digest.is_not(None),
                ActivationCodeRecord.disabled.is_(False),
            )
        elif status == "unbound":
            statement = statement.where(
                ActivationCodeRecord.device_digest.is_(None),
                ActivationCodeRecord.disabled.is_(False),
            )
        elif status == "disabled":
            statement = statement.where(ActivationCodeRecord.disabled.is_(True))
        if code_digest:
            statement = statement.where(
                ActivationCodeRecord.code_digest == code_digest
            )
        with self._database.session() as session:
            total = (
                session.scalar(
                    select(func.count()).select_from(statement.subquery())
                )
                or 0
            )
            records = session.scalars(
                statement.order_by(ActivationCodeRecord.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return tuple(
                _code_to_domain(record, self._cipher) for record in records
            ), total

    def list_code_states(self, code_ids) -> dict[str, bool]:
        """批量返回 code_id → disabled 状态（供订单页显示启停）。"""
        ids = tuple(cid for cid in code_ids if cid)
        if not ids:
            return {}
        with self._database.session() as session:
            rows = session.execute(
                select(
                    ActivationCodeRecord.code_id, ActivationCodeRecord.disabled
                ).where(ActivationCodeRecord.code_id.in_(ids))
            )
            return {code_id: disabled for code_id, disabled in rows}

    def list_code_details(self, code_ids) -> dict[str, ActivationCode]:
        ids = tuple(cid for cid in code_ids if cid)
        if not ids:
            return {}
        with self._database.session() as session:
            records = session.scalars(
                select(ActivationCodeRecord).where(
                    ActivationCodeRecord.code_id.in_(ids)
                )
            )
            return {
                record.code_id: _code_to_domain(record, self._cipher)
                for record in records
            }

    def disable_code(self, code_id: str, now: datetime) -> ActivationCode:
        with self._database.session() as session:
            record = session.get(ActivationCodeRecord, code_id)
            if record is None:
                raise ActivationNotFound("Activation code was not found")
            if not record.disabled:
                record.disabled = True
                record.disabled_at = now
            session.flush()
            return _code_to_domain(record, self._cipher)

    def enable_code(self, code_id: str) -> ActivationCode:
        with self._database.session() as session:
            record = session.get(ActivationCodeRecord, code_id)
            if record is None:
                raise ActivationNotFound("Activation code was not found")
            if record.disabled:
                record.disabled = False
                record.disabled_at = None
            session.flush()
            return _code_to_domain(record, self._cipher)

    def get_code_by_digest(self, code_digest: str) -> ActivationCode | None:
        with self._database.session() as session:
            record = session.scalar(
                select(ActivationCodeRecord).where(
                    ActivationCodeRecord.code_digest == code_digest
                )
            )
            return _code_to_domain(record, self._cipher) if record is not None else None

    def renew_code(
        self,
        code_id: str,
        duration_hours: int,
        quota: int,
        now: datetime,
    ) -> ActivationCode:
        """续购叠加：在现有激活码上累加时长/次数（不换激活码）。"""
        with self._database.session() as session:
            record = session.scalar(
                select(ActivationCodeRecord)
                .where(ActivationCodeRecord.code_id == code_id)
                .with_for_update()
            )
            if record is None:
                raise ActivationNotFound("Activation code was not found")
            if record.disabled:
                raise ActivationConflict("Activation code is disabled")
            if duration_hours > 0:
                expires_at = _as_utc(record.expires_at)
                if expires_at is None or expires_at <= now:
                    record.expires_at = now + timedelta(hours=duration_hours)
                else:
                    record.expires_at = expires_at + timedelta(hours=duration_hours)
            if quota > 0:
                record.quota_total += quota
                record.quota_remaining += quota
            session.flush()
            return _code_to_domain(record, self._cipher)

    def activate(
        self,
        code_digest: str,
        device_digest: str,
        token_digest: str,
        now: datetime,
    ) -> DeviceActivation:
        with self._activation_lock:
            try:
                with self._database.session() as session:
                    record = session.scalar(
                        select(ActivationCodeRecord)
                        .where(ActivationCodeRecord.code_digest == code_digest)
                        .with_for_update()
                    )
                    if record is None:
                        raise ActivationDenied("invalid_code", "Activation code is invalid")
                    if record.disabled:
                        raise ActivationDenied("code_disabled", "Activation code is disabled")
                    if record.device_digest is None:
                        previous = _as_utc(record.expires_at)
                        if previous is not None and previous > now:
                            expires_at = previous  # 换机续用：延续剩余时长
                        else:
                            expires_at = now + timedelta(hours=record.duration_hours)
                        claimed = session.execute(
                            update(ActivationCodeRecord)
                            .where(
                                ActivationCodeRecord.code_id == record.code_id,
                                ActivationCodeRecord.device_digest.is_(None),
                                ActivationCodeRecord.disabled.is_(False),
                            )
                            .values(
                                device_digest=device_digest,
                                activated_at=now,
                                expires_at=expires_at,
                            )
                        )
                        session.flush()
                        session.expire_all()
                        record = session.get(ActivationCodeRecord, record.code_id)
                        if claimed.rowcount != 1 or record is None:
                            raise ActivationConflict("Activation binding changed concurrently")
                    if record.device_digest != device_digest:
                        raise ActivationDenied(
                            "device_mismatch",
                            "Activation code is already bound to another device",
                        )
                    expires_at = _as_utc(record.expires_at)
                    activated_at = _as_utc(record.activated_at)
                    if expires_at is None or activated_at is None or expires_at <= now:
                        raise ActivationDenied("code_expired", "Activation code has expired")
                    record.token_digest = token_digest
                    session.flush()
                    return DeviceActivation(
                        code_id=record.code_id,
                        plan_id=record.plan_id,
                        activated_at=activated_at,
                        expires_at=expires_at,
                        quota_total=record.quota_total,
                        quota_remaining=record.quota_remaining,
                    )
            except IntegrityError as error:
                raise ActivationConflict("Device token collision") from error

    def authorize_token(self, token_digest: str, now: datetime) -> bool:
        with self._database.session() as session:
            record = session.scalar(
                select(ActivationCodeRecord).where(
                    ActivationCodeRecord.token_digest == token_digest
                )
            )
            if record is None or record.disabled:
                return False
            expires_at = _as_utc(record.expires_at)
            return expires_at is not None and expires_at > now

    def resolve_token(self, token_digest: str) -> ActivationCode | None:
        """按激活 token 查激活码（供次数查询/扣减）。"""
        with self._database.session() as session:
            record = session.scalar(
                select(ActivationCodeRecord).where(
                    ActivationCodeRecord.token_digest == token_digest
                )
            )
            return _code_to_domain(record, self._cipher) if record is not None else None

    def unbind(self, code_digest: str) -> bool:
        """自助解绑：清设备与 token 绑定，保留次数/时长额度。"""
        with self._database.session() as session:
            record = session.scalar(
                select(ActivationCodeRecord).where(
                    ActivationCodeRecord.code_digest == code_digest
                )
            )
            if record is None or record.disabled:
                return False
            record.device_digest = None
            record.token_digest = None
            session.flush()
            return True

    def get_usage(self, token_digest: str) -> tuple[int, int]:
        """返回 (quota_total, quota_remaining)。"""
        with self._database.session() as session:
            record = session.scalar(
                select(ActivationCodeRecord).where(
                    ActivationCodeRecord.token_digest == token_digest
                )
            )
            if record is None:
                return (0, 0)
            return (record.quota_total, record.quota_remaining)

    def consume_quota(
        self, token_digest: str, amount: int, now: datetime
    ) -> tuple[bool, int]:
        """原子扣减次数。返回 (是否成功, 剩余次数)；不足则 (False, 剩余)。"""
        if amount <= 0:
            return (False, 0)
        with self._activation_lock:
            with self._database.session() as session:
                record = session.scalar(
                    select(ActivationCodeRecord)
                    .where(ActivationCodeRecord.token_digest == token_digest)
                    .with_for_update()
                )
                if record is None or record.disabled or record.quota_remaining < amount:
                    remaining = record.quota_remaining if record is not None else 0
                    return (False, remaining)
                record.quota_remaining -= amount
                session.add(
                    UsageRecordRecord(
                        code_id=record.code_id, amount=amount, created_at=now
                    )
                )
                session.flush()
                return (True, record.quota_remaining)

    def list_usage(self, limit: int = 100) -> list[UsageRecord]:
        with self._database.session() as session:
            records = session.scalars(
                select(UsageRecordRecord)
                .order_by(UsageRecordRecord.created_at.desc())
                .limit(limit)
            )
            return [
                UsageRecord(
                    usage_id=record.usage_id,
                    code_id=record.code_id,
                    amount=record.amount,
                    created_at=_as_utc(record.created_at) or record.created_at,
                )
                for record in records
            ]

    def list_usage_page(
        self,
        page: int = 1,
        page_size: int = 50,
        code_digest: str | None = None,
    ) -> tuple[list[UsageRecord], int]:
        """分页查询用量记录，可按激活码摘要精确过滤。返回 (记录, 总数)。"""
        statement = select(
            UsageRecordRecord, ActivationCodeRecord.code_plaintext_cipher
        ).join(
            ActivationCodeRecord,
            UsageRecordRecord.code_id == ActivationCodeRecord.code_id,
        )
        if code_digest:
            statement = statement.where(
                ActivationCodeRecord.code_digest == code_digest
            )
        with self._database.session() as session:
            total = (
                session.scalar(
                    select(func.count()).select_from(statement.subquery())
                )
                or 0
            )
            rows = session.execute(
                statement.order_by(UsageRecordRecord.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [
                UsageRecord(
                    usage_id=record.usage_id,
                    code_id=record.code_id,
                    amount=record.amount,
                    created_at=_as_utc(record.created_at) or record.created_at,
                    plaintext=_decrypt_plaintext(self._cipher, plaintext_cipher),
                )
                for record, plaintext_cipher in rows
            ], total


def _plan_to_domain(record: ActivationPlanRecord) -> ActivationPlan:
    return ActivationPlan(
        plan_id=record.plan_id,
        values=ActivationPlanValues(
            name=record.name,
            amount_minor=record.amount_minor,
            currency=record.currency,
            duration_hours=record.duration_hours,
            enabled=record.enabled,
            plan_type=record.plan_type,
            quota=record.quota,
            sale_amount_minor=record.sale_amount_minor,
            sale_ends_at=_as_utc(record.sale_ends_at),
            benefits=record.benefits or "",
        ),
        created_at=_as_utc(record.created_at) or record.created_at,
        updated_at=_as_utc(record.updated_at) or record.updated_at,
    )


def _code_to_domain(
    record: ActivationCodeRecord, cipher: SecretsCipher | None = None
) -> ActivationCode:
    return ActivationCode(
        code_id=record.code_id,
        plan_id=record.plan_id,
        duration_hours=record.duration_hours,
        disabled=record.disabled,
        bound=record.device_digest is not None,
        created_at=_as_utc(record.created_at) or record.created_at,
        activated_at=_as_utc(record.activated_at),
        expires_at=_as_utc(record.expires_at),
        disabled_at=_as_utc(record.disabled_at),
        quota_total=record.quota_total,
        quota_remaining=record.quota_remaining,
        plaintext=_decrypt_plaintext(cipher, record.code_plaintext_cipher),
    )


def _decrypt_plaintext(
    cipher: SecretsCipher | None, token: str | None
) -> str | None:
    if cipher is None or not token:
        return None
    try:
        return cipher.decrypt(token)
    except ValueError:
        return None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
