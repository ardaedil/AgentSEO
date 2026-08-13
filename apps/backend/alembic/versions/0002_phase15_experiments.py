"""Phase 1.5 experimental validation schema.

Revision ID: 0002
Revises: 0001
"""

from agentseo import models  # noqa: F401
from agentseo.database import Base
from alembic import op
from sqlalchemy import inspect

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Bring databases created by the Phase 1 metadata migration up to date.

    Revision 0001 intentionally used ``metadata.create_all``. On a fresh install it
    therefore sees the current metadata, while an existing Phase 1 database needs
    additive columns and tables. The inspection guards make both paths safe.
    """

    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    Base.metadata.create_all(bind=bind)

    additions = {
        "interface_versions": [
            ("name", "VARCHAR(200) NOT NULL DEFAULT 'Canonical baseline'"),
            ("variant_key", "VARCHAR(80) NOT NULL DEFAULT 'baseline'"),
            ("frozen", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ],
        "benchmark_tasks": [("phase15_split", "VARCHAR(20)")],
        "benchmark_runs": [
            ("experiment_id", "VARCHAR(36) REFERENCES experiments(id)"),
            ("trial_number", "INTEGER NOT NULL DEFAULT 1"),
            ("task_split", "VARCHAR(20)"),
        ],
        "task_runs": [
            ("experiment_id", "VARCHAR(36) REFERENCES experiments(id)"),
            ("interface_version_id", "VARCHAR(36) REFERENCES interface_versions(id)"),
            ("model_identifier", "VARCHAR(200) NOT NULL DEFAULT ''"),
            ("task_version", "INTEGER NOT NULL DEFAULT 1"),
            ("trial_number", "INTEGER NOT NULL DEFAULT 1"),
            ("task_split", "VARCHAR(20)"),
            ("temperature", "FLOAT"),
            ("provider_seed", "INTEGER"),
        ],
    }
    for table, columns in additions.items():
        if table not in existing_tables:
            continue
        current = {column["name"] for column in inspect(bind).get_columns(table)}
        for name, ddl in columns:
            if name not in current:
                op.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def downgrade() -> None:
    # SQLite cannot safely drop these additive columns without table recreation.
    for table in ("experiment_results", "interface_mutations", "experiments"):
        if table in inspect(op.get_bind()).get_table_names():
            op.drop_table(table)
