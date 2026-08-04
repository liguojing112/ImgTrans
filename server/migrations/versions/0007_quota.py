"""Add quota (usage-based) plans, code quota and usage records.

Revision ID: 0007_quota
Revises: 0006_payments
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_quota"
down_revision: Union[str, None] = "0006_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activation_plans",
        sa.Column(
            "plan_type",
            sa.String(length=10),
            nullable=False,
            server_default="duration",
        ),
    )
    op.add_column(
        "activation_plans",
        sa.Column(
            "quota",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "activation_codes",
        sa.Column(
            "quota_total",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "activation_codes",
        sa.Column(
            "quota_remaining",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "usage_records",
        sa.Column("usage_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code_id", sa.String(length=36), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["code_id"], ["activation_codes.code_id"]),
        sa.PrimaryKeyConstraint("usage_id"),
    )
    op.create_index(
        "ix_usage_records_code_id", "usage_records", ["code_id"], unique=False
    )
    op.create_index(
        "ix_usage_records_created_at", "usage_records", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_created_at", table_name="usage_records")
    op.drop_index("ix_usage_records_code_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_column("activation_codes", "quota_remaining")
    op.drop_column("activation_codes", "quota_total")
    op.drop_column("activation_plans", "quota")
    op.drop_column("activation_plans", "plan_type")
