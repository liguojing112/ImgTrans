"""Add hidden flag to activation plans (hidden plans are not listed for clients).

Revision ID: 0017_activation_plan_hidden
Revises: 0016_activation_plan_promotion_schedule
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_activation_plan_hidden"
down_revision: Union[str, None] = "0016_activation_plan_promotion_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activation_plans",
        sa.Column(
            "hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("activation_plans", "hidden")
