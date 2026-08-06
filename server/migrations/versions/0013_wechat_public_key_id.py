"""Add wechat public key id (wechatpayv3 public-key mode).

Revision ID: 0013_wechat_public_key_id
Revises: 0012_plan_hours
Create Date: 2026-08-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_wechat_public_key_id"
down_revision: Union[str, None] = "0012_plan_hours"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "service_settings",
        sa.Column("wechat_public_key_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_settings", "wechat_public_key_id")
