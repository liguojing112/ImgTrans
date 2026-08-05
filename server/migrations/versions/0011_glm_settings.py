"""Add GLM (product copywriting) settings to service settings.

Revision ID: 0011_glm_settings
Revises: 0010_activation_code_plaintext
Create Date: 2026-08-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_glm_settings"
down_revision: Union[str, None] = "0010_activation_code_plaintext"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "service_settings",
        sa.Column("glm_api_key_cipher", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "service_settings",
        sa.Column("glm_model", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_settings", "glm_model")
    op.drop_column("service_settings", "glm_api_key_cipher")
