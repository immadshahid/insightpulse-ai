"""initial schema: users, datasets, charts

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "datasets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_key", sa.String(255), nullable=False),
        sa.Column("clean_key", sa.String(255), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile", JSON, nullable=True),
        sa.Column("mapping", JSON, nullable=True),
        sa.Column("cleaning", JSON, nullable=True),
        sa.Column("quality", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_datasets_user_id", "datasets", ["user_id"])

    op.create_table(
        "charts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(32),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_charts_dataset_id", "charts", ["dataset_id"])
    op.create_index("ix_charts_user_id", "charts", ["user_id"])


def downgrade() -> None:
    op.drop_table("charts")
    op.drop_table("datasets")
    op.drop_table("users")
