"""Rename duration unit from days to hours.

Revision ID: 0012_plan_hours
Revises: 0011_glm_settings
Create Date: 2026-08-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_plan_hours"
down_revision: Union[str, None] = "0011_glm_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("activation_plans") as batch:
        batch.alter_column("duration_days", new_column_name="duration_hours")
        batch.drop_constraint("ck_activation_plan_duration", type_="check")
        batch.create_check_constraint(
            "ck_activation_plan_duration",
            "duration_hours >= 0 AND duration_hours <= 87600",
        )
    with op.batch_alter_table("activation_codes") as batch:
        batch.alter_column("duration_days", new_column_name="duration_hours")
        batch.drop_constraint("ck_activation_code_duration", type_="check")
        batch.create_check_constraint(
            "ck_activation_code_duration",
            "duration_hours >= 0 AND duration_hours <= 87600",
        )


def downgrade() -> None:
    with op.batch_alter_table("activation_codes") as batch:
        batch.drop_constraint("ck_activation_code_duration", type_="check")
        batch.create_check_constraint(
            "ck_activation_code_duration",
            "duration_days >= 1 AND duration_days <= 3650",
        )
        batch.alter_column("duration_hours", new_column_name="duration_days")
    with op.batch_alter_table("activation_plans") as batch:
        batch.drop_constraint("ck_activation_plan_duration", type_="check")
        batch.create_check_constraint(
            "ck_activation_plan_duration",
            "duration_days >= 1 AND duration_days <= 3650",
        )
        batch.alter_column("duration_hours", new_column_name="duration_days")
