"""Add recurring selected-date promotion schedules.

Revision ID: 0016_activation_plan_promotion_schedule
Revises: 0015_payment_refunded_status
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_activation_plan_promotion_schedule"
down_revision: Union[str, None] = "0015_payment_refunded_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activation_plans", sa.Column("sale_dates_json", sa.String(2048), nullable=True)
    )
    op.add_column(
        "activation_plans", sa.Column("sale_start_time", sa.String(5), nullable=True)
    )
    op.add_column(
        "activation_plans", sa.Column("sale_end_time", sa.String(5), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("activation_plans", "sale_end_time")
    op.drop_column("activation_plans", "sale_start_time")
    op.drop_column("activation_plans", "sale_dates_json")
