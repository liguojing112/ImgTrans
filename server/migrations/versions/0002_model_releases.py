"""Create model release metadata.

Revision ID: 0002_model_releases
Revises: 0001_image_limit_versions
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_model_releases"
down_revision: Union[str, None] = "0001_image_limit_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_releases",
        sa.Column("release_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("architecture", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("object_version", sa.String(length=256), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size_bytes > 0", name="ck_model_release_size"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn')",
            name="ck_model_release_status",
        ),
        sa.PrimaryKeyConstraint("release_id"),
        sa.UniqueConstraint(
            "model_id", "version", "platform", "architecture",
            name="uq_model_release_target_version",
        ),
    )
    op.create_index(
        "ix_model_release_manifest",
        "model_releases",
        ["platform", "architecture", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_model_release_manifest", table_name="model_releases")
    op.drop_table("model_releases")
