"""Add promotion price, deadline and benefits to activation plans.

Revision ID: 0008_promotion
Revises: 0007_quota
Create Date: 2026-08-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_promotion"
down_revision: Union[str, None] = "0007_quota"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activation_plans",
        sa.Column("sale_amount_minor", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "activation_plans",
        sa.Column("sale_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "activation_plans",
        sa.Column("benefits", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activation_plans", "benefits")
    op.drop_column("activation_plans", "sale_ends_at")
    op.drop_column("activation_plans", "sale_amount_minor")
