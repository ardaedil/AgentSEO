"""Phase 1 schema

Revision ID: 0001
"""

from agentseo import models  # noqa: F401
from agentseo.database import Base
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
