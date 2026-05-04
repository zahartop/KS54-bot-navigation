"""telegram_users.is_admin for RBAC (админ-панель /admin).

Revision ID: j5k6l7m8n9p0
Revises: h3k5m7n9p0q1

После upgrade выдайте права вручную, например:
  UPDATE telegram_users SET is_admin = true WHERE telegram_user_id = <ваш_telegram_id>;
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j5k6l7m8n9p0"
down_revision: Union[str, None] = "h3k5m7n9p0q1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("telegram_users")}
    if "is_admin" not in cols:
        op.add_column(
            "telegram_users",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("telegram_users")}
    if "is_admin" in cols:
        op.drop_column("telegram_users", "is_admin")
