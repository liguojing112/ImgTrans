"""Add base_url to GLM (product copywriting) settings for custom OpenAI-compatible LLMs.

Revision ID: 0018_glm_base_url
Revises: 0017_activation_plan_hidden
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_glm_base_url"
down_revision: Union[str, None] = "0017_activation_plan_hidden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "service_settings",
        sa.Column("glm_base_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_settings", "glm_base_url")
