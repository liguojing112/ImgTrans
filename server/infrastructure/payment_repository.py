"""支付订单持久化 — SQLAlchemy 实现。"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Integer, String, func, or_, select, update
from sqlalchemy.orm import Mapped, mapped_column

from server.domain.payment import PaymentOrder, PaymentStatus
from server.infrastructure.activation_repository import ActivationCodeRecord
from server.infrastructure.database import Base, Database


class PaymentOrderRecord(Base):
    __tablename__ = "payment_orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_type: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    code_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    activation_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlAlchemyPaymentRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, order: PaymentOrder) -> PaymentOrder:
        record = PaymentOrderRecord(
            order_id=order.order_id,
            plan_id=order.plan_id,
            plan_type=order.plan_type,
            amount_minor=order.amount_minor,
            currency=order.currency,
            status=order.status.value,
            code_id=order.code_id,
            activation_code=order.activation_code,
            created_at=order.created_at,
            paid_at=order.paid_at,
        )
        with self._database.session() as session:
            session.add(record)
        return order

    def get(self, order_id: str) -> PaymentOrder | None:
        with self._database.session() as session:
            record = session.get(PaymentOrderRecord, order_id)
            return _to_order(record) if record is not None else None

    def mark_paid_if_created(self, order_id: str, now: datetime) -> bool:
        """仅当订单仍为 created 时置为 paid；返回是否发生状态迁移（幂等首跳）。"""
        with self._database.session() as session:
            result = session.execute(
                update(PaymentOrderRecord)
                .where(
                    PaymentOrderRecord.order_id == order_id,
                    PaymentOrderRecord.status == PaymentStatus.CREATED.value,
                )
                .values(status=PaymentStatus.PAID.value, paid_at=now)
            )
            return result.rowcount > 0

    def set_activation_code(
        self, order_id: str, code_id: str, activation_code: str, now: datetime
    ) -> None:
        with self._database.session() as session:
            session.execute(
                update(PaymentOrderRecord)
                .where(PaymentOrderRecord.order_id == order_id)
                .values(code_id=code_id, activation_code=activation_code, paid_at=now)
            )

    def list_recent(self, limit: int = 100) -> list[PaymentOrder]:
        with self._database.session() as session:
            records = session.scalars(
                select(PaymentOrderRecord)
                .order_by(PaymentOrderRecord.created_at.desc())
                .limit(limit)
            ).all()
            return [_to_order(record) for record in records]

    def list_page(
        self,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
        activation_code: str | None = None,
        status: str | None = None,
        amount_minor: int | None = None,
    ) -> tuple[list[PaymentOrder], int]:
        """分页查询订单，可按订单号或激活码搜索。返回 (订单列表, 总数)。"""
        with self._database.session() as session:
            statement = select(PaymentOrderRecord)
            if search:
                like = f"%{search.strip()}%"
                statement = statement.where(
                    or_(
                        PaymentOrderRecord.order_id.ilike(like),
                        PaymentOrderRecord.activation_code.ilike(like),
                    )
                )
            if activation_code:
                statement = statement.where(
                    PaymentOrderRecord.activation_code.ilike(
                        f"%{activation_code.strip()}%"
                    )
                )
            if amount_minor is not None:
                statement = statement.where(
                    PaymentOrderRecord.amount_minor == amount_minor
                )
            if status == "refunded":
                statement = (
                    statement.join(
                        ActivationCodeRecord,
                        ActivationCodeRecord.code_id == PaymentOrderRecord.code_id,
                    )
                    .where(
                        PaymentOrderRecord.status == PaymentStatus.PAID.value,
                        ActivationCodeRecord.disabled.is_(True),
                    )
                )
            elif status in {item.value for item in PaymentStatus}:
                statement = statement.where(PaymentOrderRecord.status == status)
            total = (
                session.scalar(select(func.count()).select_from(statement.subquery()))
                or 0
            )
            records = session.scalars(
                statement.order_by(PaymentOrderRecord.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [_to_order(record) for record in records], total

    def list_amounts(self) -> tuple[tuple[int, str], ...]:
        with self._database.session() as session:
            rows = session.execute(
                select(PaymentOrderRecord.amount_minor, PaymentOrderRecord.currency)
                .distinct()
                .order_by(
                    PaymentOrderRecord.currency,
                    PaymentOrderRecord.amount_minor,
                )
            ).all()
            return tuple((amount_minor, currency) for amount_minor, currency in rows)


def _to_order(record: PaymentOrderRecord) -> PaymentOrder:
    return PaymentOrder(
        order_id=record.order_id,
        plan_id=record.plan_id,
        amount_minor=record.amount_minor,
        currency=record.currency,
        status=PaymentStatus(record.status),
        code_id=record.code_id,
        created_at=record.created_at,
        paid_at=record.paid_at,
        activation_code=record.activation_code,
        plan_type=record.plan_type,
    )
