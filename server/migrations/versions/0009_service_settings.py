"""Create service_settings table for backend-managed third-party config.

Revision ID: 0009_service_settings
Revises: 0008_promotion
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_service_settings"
down_revision: Union[str, None] = "0008_promotion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wechat_appid", sa.String(length=64), nullable=True),
        sa.Column("wechat_mchid", sa.String(length=64), nullable=True),
        sa.Column("wechat_apiv3_key_cipher", sa.String(length=500), nullable=True),
        sa.Column("wechat_private_key_cipher", sa.String(length=4000), nullable=True),
        sa.Column("wechat_serial_no", sa.String(length=64), nullable=True),
        sa.Column("wechat_platform_cert_cipher", sa.String(length=4000), nullable=True),
        sa.Column("wechat_notify_url", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("service_settings")
