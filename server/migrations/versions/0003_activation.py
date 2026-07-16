"""Create activation plans and activation codes.

Revision ID: 0003_activation
Revises: 0002_model_releases
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_activation"
down_revision: Union[str, None] = "0002_model_releases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activation_plans",
        sa.Column("plan_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor >= 0", name="ck_activation_plan_amount"),
        sa.CheckConstraint(
            "duration_days >= 1 AND duration_days <= 3650",
            name="ck_activation_plan_duration",
        ),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_table(
        "activation_codes",
        sa.Column("code_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("device_digest", sa.String(length=64), nullable=True),
        sa.Column("token_digest", sa.String(length=64), nullable=True),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "duration_days >= 1 AND duration_days <= 3650",
            name="ck_activation_code_duration",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["activation_plans.plan_id"]),
        sa.PrimaryKeyConstraint("code_id"),
        sa.UniqueConstraint("code_digest", name="uq_activation_code_digest"),
        sa.UniqueConstraint("token_digest", name="uq_activation_token_digest"),
    )
    op.create_index(
        "ix_activation_codes_plan_id",
        "activation_codes",
        ["plan_id"],
        unique=False,
    )
    op.create_index(
        "ix_activation_codes_expires_at",
        "activation_codes",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_activation_codes_expires_at", table_name="activation_codes")
    op.drop_index("ix_activation_codes_plan_id", table_name="activation_codes")
    op.drop_table("activation_codes")
    op.drop_table("activation_plans")
