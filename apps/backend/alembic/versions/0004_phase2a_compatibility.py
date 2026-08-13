"""Add Phase 2A behavioral compatibility CI models.

Revision ID: 0004_phase2a_compatibility
Revises: 0003_task_family
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0004_phase2a_compatibility"
down_revision: str | None = "0003_task_family"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "compatibility_runs" not in tables:
        op.create_table(
            "compatibility_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("repository", sa.String(300), nullable=False),
            sa.Column("base_ref", sa.String(250), nullable=False),
            sa.Column("candidate_ref", sa.String(250), nullable=False),
            sa.Column("base_commit", sa.String(80)),
            sa.Column("candidate_commit", sa.String(80)),
            sa.Column(
                "baseline_interface_version_id",
                sa.String(36),
                sa.ForeignKey("interface_versions.id"),
                nullable=False,
            ),
            sa.Column(
                "candidate_interface_version_id",
                sa.String(36),
                sa.ForeignKey("interface_versions.id"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("models", sa.JSON(), nullable=False),
            sa.Column("task_suite_id", sa.String(300), nullable=False),
            sa.Column("test_selection_strategy", sa.String(40), nullable=False),
            sa.Column("estimated_cost", sa.Float(), nullable=False),
            sa.Column("actual_cost", sa.Float(), nullable=False),
            sa.Column("verdict", sa.String(30)),
            sa.Column("release_classification", sa.String(40)),
            sa.Column("metadata", sa.JSON(), nullable=False),
        )
    if "compatibility_results" not in tables:
        op.create_table(
            "compatibility_results",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "compatibility_run_id",
                sa.String(36),
                sa.ForeignKey("compatibility_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("model", sa.String(200), nullable=False),
            sa.Column("task_id", sa.String(36), nullable=False),
            sa.Column("baseline_task_run_id", sa.String(36), sa.ForeignKey("task_runs.id")),
            sa.Column("candidate_task_run_id", sa.String(36), sa.ForeignKey("task_runs.id")),
            sa.Column("baseline_success", sa.Boolean(), nullable=False),
            sa.Column("candidate_success", sa.Boolean(), nullable=False),
            sa.Column("baseline_failure", sa.String(80)),
            sa.Column("candidate_failure", sa.String(80)),
            sa.Column("baseline_tool_calls", sa.Integer(), nullable=False),
            sa.Column("candidate_tool_calls", sa.Integer(), nullable=False),
            sa.Column("baseline_tokens", sa.Integer(), nullable=False),
            sa.Column("candidate_tokens", sa.Integer(), nullable=False),
            sa.Column("baseline_latency", sa.Float(), nullable=False),
            sa.Column("candidate_latency", sa.Float(), nullable=False),
            sa.Column("baseline_cost", sa.Float(), nullable=False),
            sa.Column("candidate_cost", sa.Float(), nullable=False),
            sa.Column("safety_baseline", sa.Boolean(), nullable=False),
            sa.Column("safety_candidate", sa.Boolean(), nullable=False),
            sa.Column("regression_type", sa.String(80)),
            sa.Column("details", sa.JSON(), nullable=False),
        )
    indexes = {index["name"] for index in inspect(bind).get_indexes("compatibility_results")}
    if "ix_compatibility_results_compatibility_run_id" not in indexes:
        op.create_index(
            "ix_compatibility_results_compatibility_run_id",
            "compatibility_results",
            ["compatibility_run_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_compatibility_results_compatibility_run_id", table_name="compatibility_results"
    )
    op.drop_table("compatibility_results")
    op.drop_table("compatibility_runs")
