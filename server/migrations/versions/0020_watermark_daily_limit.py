"""Add per-plan daily watermark-removal limit and per-code daily counter.

套餐新增「去水印（张/日）」属性（0=该套餐不含），扣减时实时按激活码所属
套餐读取上限；激活码记录每日已用张数与归属北京日期，跨日自动清零。

Revision ID: 0020_watermark_daily_limit
Revises: 0019_translation_llm
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_watermark_daily_limit"
down_revision: Union[str, None] = "0019_translation_llm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activation_plans",
        sa.Column(
            "watermark_daily_limit",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "activation_codes",
        sa.Column(
            "watermark_used_today",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "activation_codes",
        sa.Column("watermark_used_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activation_codes", "watermark_used_date")
    op.drop_column("activation_codes", "watermark_used_today")
    op.drop_column("activation_plans", "watermark_daily_limit")
