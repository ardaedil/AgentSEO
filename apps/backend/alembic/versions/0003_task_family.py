"""Add first-class task-family membership.

Revision ID: 0003_task_family
Revises: 0002_phase15_experiments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0003_task_family"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("benchmark_tasks")}
    if "task_family" not in columns:
        op.add_column(
            "benchmark_tasks",
            sa.Column(
                "task_family", sa.String(length=120), nullable=False, server_default="unassigned"
            ),
        )
    indexes = {index["name"] for index in inspect(bind).get_indexes("benchmark_tasks")}
    if "ix_benchmark_tasks_task_family" not in indexes:
        op.create_index("ix_benchmark_tasks_task_family", "benchmark_tasks", ["task_family"])


def downgrade() -> None:
    op.drop_index("ix_benchmark_tasks_task_family", table_name="benchmark_tasks")
    op.drop_column("benchmark_tasks", "task_family")
