"""Create payment orders for WeChat Pay Native.

Revision ID: 0006_payments
Revises: 0005_admin_users
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_payments"
down_revision: Union[str, None] = "0005_admin_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_orders",
        sa.Column("order_id", sa.String(length=32), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("code_id", sa.String(length=36), nullable=True),
        sa.Column("activation_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount_minor >= 0", name="ck_payment_order_amount"
        ),
        sa.CheckConstraint(
            "status IN ('created', 'paid', 'cancelled')",
            name="ck_payment_order_status",
        ),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index(
        "ix_payment_orders_created_at",
        "payment_orders",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payment_orders_created_at", table_name="payment_orders")
    op.drop_table("payment_orders")
