"""Persist activation-plan type on payment orders.

Revision ID: 0014_payment_order_plan_type
Revises: 0013_wechat_public_key_id
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_payment_order_plan_type"
down_revision: Union[str, None] = "0013_wechat_public_key_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_orders",
        sa.Column(
            "plan_type",
            sa.String(length=10),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.execute(
        """
        UPDATE payment_orders
        SET plan_type = (
            SELECT plan_type
            FROM activation_plans
            WHERE activation_plans.plan_id = payment_orders.plan_id
        )
        WHERE EXISTS (
            SELECT 1
            FROM activation_plans
            WHERE activation_plans.plan_id = payment_orders.plan_id
        )
        """
    )
    op.alter_column("payment_orders", "plan_type", server_default=None)


def downgrade() -> None:
    op.drop_column("payment_orders", "plan_type")
