"""add telegram_users is_policy_accepted + backfill from pd_consents

Revision ID: g2h4i6j8k0l1
Revises: f7e8d9c0b1a2
Create Date: 2026-05-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g2h4i6j8k0l1"
down_revision: Union[str, None] = "f7e8d9c0b1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "telegram_users" not in existing:
        op.create_table(
            "telegram_users",
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
            sa.Column(
                "is_policy_accepted",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("telegram_user_id"),
        )

    op.execute(
        sa.text("""
            INSERT INTO telegram_users (telegram_user_id, is_policy_accepted)
            SELECT DISTINCT telegram_user_id, TRUE
            FROM pd_consents
            ON CONFLICT (telegram_user_id) DO UPDATE
            SET is_policy_accepted = TRUE
        """)
    )


def downgrade() -> None:
    op.drop_table("telegram_users")
