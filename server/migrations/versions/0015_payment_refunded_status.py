"""Allow 'refunded' status on payment orders (admin refund action).

Revision ID: 0015_payment_refunded_status
Revises: 0014_payment_order_plan_type
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_payment_refunded_status"
down_revision: Union[str, None] = "0014_payment_order_plan_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_payment_order_status", "payment_orders", type_="check")
    op.create_check_constraint(
        "ck_payment_order_status",
        "payment_orders",
        "status IN ('created', 'paid', 'cancelled', 'refunded')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payment_order_status", "payment_orders", type_="check")
    op.create_check_constraint(
        "ck_payment_order_status",
        "payment_orders",
        "status IN ('created', 'paid', 'cancelled')",
    )
