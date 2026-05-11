"""Add saved_fio, saved_phone, saved_email to telegram_users

Revision ID: k7l8m9n0p1q2
Revises: h3k5m7n9p0q1
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k7l8m9n0p1q2"
down_revision: Union[str, None] = "j5k6l7m8n9p0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("telegram_users")}

    if "saved_fio" not in columns:
        op.add_column("telegram_users", sa.Column("saved_fio", sa.String(200), nullable=True))
    if "saved_phone" not in columns:
        op.add_column("telegram_users", sa.Column("saved_phone", sa.String(20), nullable=True))
    if "saved_email" not in columns:
        op.add_column("telegram_users", sa.Column("saved_email", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("telegram_users", "saved_email")
    op.drop_column("telegram_users", "saved_phone")
    op.drop_column("telegram_users", "saved_fio")
