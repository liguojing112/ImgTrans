"""Create portal module entries (client-facing entry cards).

Revision ID: 0005_portal_modules
Revises: 0004_audit_events
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_portal_modules"
down_revision: Union[str, None] = "0004_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portal_modules",
        sa.Column("module_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=False),
        sa.Column("image_url", sa.String(length=512), nullable=False),
        sa.Column("link_url", sa.String(length=512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("module_key"),
    )


def downgrade() -> None:
    op.drop_table("portal_modules")
