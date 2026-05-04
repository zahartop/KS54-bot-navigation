"""broadcast_recovery_jobs for self-healing resume prompts

Revision ID: h3k5m7n9p0q1
Revises: g2h4i6j8k0l1
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h3k5m7n9p0q1"
down_revision: Union[str, None] = "g2h4i6j8k0l1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    names = set(sa.inspect(bind).get_table_names())

    if "broadcast_recovery_jobs" not in names:
        op.create_table(
            "broadcast_recovery_jobs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("admin_chat_id", sa.BigInteger(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("payload_text", sa.Text(), nullable=True),
            sa.Column("payload_photo_file_id", sa.String(length=256), nullable=True),
            sa.Column("recipient_count_snap", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
                onupdate=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    op.drop_table("broadcast_recovery_jobs")
