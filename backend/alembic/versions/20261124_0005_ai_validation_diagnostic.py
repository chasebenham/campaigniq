"""Keep redacted validation diagnostics on AI attempts."""

import sqlalchemy as sa
from alembic import op

revision = "20261124_0005"
down_revision = "20261123_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_analyses", sa.Column("validation_diagnostic", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("ai_analyses", "validation_diagnostic")
