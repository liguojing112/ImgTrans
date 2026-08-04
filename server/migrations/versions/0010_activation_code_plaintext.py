"""Store encrypted activation code plaintext for admin display.

Revision ID: 0010_activation_code_plaintext
Revises: 0009_service_settings
Create Date: 2026-08-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_activation_code_plaintext"
down_revision: Union[str, None] = "0009_service_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activation_codes",
        sa.Column("code_plaintext_cipher", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("activation_codes", "code_plaintext_cipher")
