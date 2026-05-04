"""add telegram_user_id and pd_consents

Revision ID: c8f3a2b1d9e5
Revises: a29d64643ce3
Create Date: 2026-05-02

Changes:
  - open_day_applications: add telegram_user_id (BigInteger, nullable)
  - specialty_requests:     add telegram_user_id (BigInteger, nullable)
  - Create table pd_consents
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8f3a2b1d9e5"
down_revision = "a29d64643ce3"
branch_labels = None
depends_on = None


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _index_exists(bind, table: str, index_name: str) -> bool:
    insp = sa.inspect(bind)
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    if "pd_consents" not in existing_tables:
        op.create_table(
            "pd_consents",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
            sa.Column("form_type", sa.String(length=20), nullable=False),
            sa.Column(
                "consented_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "policy_version",
                sa.String(length=20),
                server_default="v1",
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_pd_consents_telegram_user_id", "pd_consents", ["telegram_user_id"])
        op.create_index("ix_pd_consents_consented_at", "pd_consents", ["consented_at"])

    if not _column_exists(bind, "open_day_applications", "telegram_user_id"):
        op.add_column(
            "open_day_applications",
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        )
    if not _index_exists(bind, "open_day_applications", "ix_open_day_applications_telegram_user_id"):
        op.create_index(
            "ix_open_day_applications_telegram_user_id",
            "open_day_applications",
            ["telegram_user_id"],
        )

    if not _column_exists(bind, "specialty_requests", "telegram_user_id"):
        op.add_column(
            "specialty_requests",
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        )
    if not _index_exists(bind, "specialty_requests", "ix_specialty_requests_telegram_user_id"):
        op.create_index(
            "ix_specialty_requests_telegram_user_id",
            "specialty_requests",
            ["telegram_user_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_specialty_requests_telegram_user_id", table_name="specialty_requests")
    op.drop_column("specialty_requests", "telegram_user_id")

    op.drop_index(
        "ix_open_day_applications_telegram_user_id",
        table_name="open_day_applications",
    )
    op.drop_column("open_day_applications", "telegram_user_id")

    op.drop_index("ix_pd_consents_consented_at", table_name="pd_consents")
    op.drop_index("ix_pd_consents_telegram_user_id", table_name="pd_consents")
    op.drop_table("pd_consents")
