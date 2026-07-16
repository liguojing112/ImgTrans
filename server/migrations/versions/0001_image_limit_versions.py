"""Create versioned image limits.

Revision ID: 0001_image_limit_versions
Revises:
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_image_limit_versions"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "image_limit_versions",
        sa.Column("version", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("min_width", sa.Integer(), nullable=False),
        sa.Column("min_height", sa.Integer(), nullable=False),
        sa.Column("max_width", sa.Integer(), nullable=False),
        sa.Column("max_height", sa.Integer(), nullable=False),
        sa.Column("max_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.CheckConstraint("min_width > 0", name="ck_image_limits_min_width"),
        sa.CheckConstraint("min_height > 0", name="ck_image_limits_min_height"),
        sa.CheckConstraint(
            "max_width >= min_width", name="ck_image_limits_widths"
        ),
        sa.CheckConstraint(
            "max_height >= min_height", name="ck_image_limits_heights"
        ),
        sa.CheckConstraint("max_bytes > 0", name="ck_image_limits_max_bytes"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'superseded')",
            name="ck_image_limits_status",
        ),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_index(
        "ix_image_limit_versions_status",
        "image_limit_versions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_image_limits_single_published",
        "image_limit_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_image_limits_single_published",
        table_name="image_limit_versions",
    )
    op.drop_index(
        "ix_image_limit_versions_status",
        table_name="image_limit_versions",
    )
    op.drop_table("image_limit_versions")
