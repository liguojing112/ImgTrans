"""Split image-translation LLM settings from product-copywriting (GLM) settings.

图片翻译（文本模型）与商品详情生成（视觉模型）需求强弱不同，允许分别配置
模型 / 接口地址 / 密钥；图片翻译未单独配置时回退沿用 glm_* 配置。

Revision ID: 0019_translation_llm
Revises: 0018_glm_base_url
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_translation_llm"
down_revision: Union[str, None] = "0018_glm_base_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "service_settings",
        sa.Column("translation_llm_api_key_cipher", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "service_settings",
        sa.Column("translation_llm_model", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "service_settings",
        sa.Column("translation_llm_base_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_settings", "translation_llm_base_url")
    op.drop_column("service_settings", "translation_llm_model")
    op.drop_column("service_settings", "translation_llm_api_key_cipher")
