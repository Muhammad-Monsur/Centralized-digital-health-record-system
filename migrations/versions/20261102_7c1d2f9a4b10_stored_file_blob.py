"""stored_file_blob: optional database copy of uploaded documents (FILE_STORAGE=database)

Revision ID: 7c1d2f9a4b10
Revises: 509aa794a811
Create Date: 2026-11-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "7c1d2f9a4b10"
down_revision = "509aa794a811"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_file_blob",
        sa.Column("stored_name", sa.String(48), primary_key=True),
        sa.Column("data", sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("stored_file_blob")
