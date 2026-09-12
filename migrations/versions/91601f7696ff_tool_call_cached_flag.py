"""Record whether a tool call was served from cache.

Autogeneration was run against SQLite and proposed a batch of NUMERIC → UUID
type changes as well. Those are an artefact of SQLite having no native UUID
type: on PostgreSQL the columns are already ``uuid``, so the alterations would
be noise at best and a table rewrite at worst. Only the new column is kept.

Revision ID: 91601f7696ff
Revises: 46524fabd6fa
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "91601f7696ff"
down_revision: str | None = "46524fabd6fa"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # The server_default lets the column be NOT NULL on a table that already
    # has rows — existing calls predate caching and were, by definition, not
    # served from it. It is left in place rather than dropped afterwards:
    # SQLite cannot ALTER a default, and the tests run these same migrations
    # against SQLite. A false default on a boolean the application always
    # supplies costs nothing.
    op.add_column(
        "tool_calls",
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("tool_calls", "cached")
