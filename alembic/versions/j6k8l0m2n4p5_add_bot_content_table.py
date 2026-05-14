"""add bot_content for dynamic CMS / Docflow thin client

Revision ID: j6k8l0m2n4p5
Revises: k7l8m9n0p1q2
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "j6k8l0m2n4p5"
down_revision: Union[str, None] = "k7l8m9n0p1q2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    names = set(sa.inspect(bind).get_table_names())
    if "bot_content" in names:
        return
    op.create_table(
        "bot_content",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "buttons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_bot_content_slug"),
    )
    op.create_index("ix_bot_content_slug", "bot_content", ["slug"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bot_content_slug", table_name="bot_content")
    op.drop_table("bot_content")
