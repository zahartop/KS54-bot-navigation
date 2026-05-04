"""initial

Revision ID: a29d64643ce3
Revises:
Create Date: 2026-05-02

Creates tables: open_day_applications, specialty_requests (with indexes).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a29d64643ce3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Таблицы могли быть созданы до Alembic (create_all). Не дублируем DDL.
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "open_day_applications" not in existing:
        op.create_table(
            "open_day_applications",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("fio", sa.String(length=100), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("phone", sa.String(length=20), nullable=False),
            sa.Column("date", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_open_day_applications_phone", "open_day_applications", ["phone"])
        op.create_index("ix_open_day_applications_email", "open_day_applications", ["email"])
        op.create_index(
            "ix_open_day_applications_created_at",
            "open_day_applications",
            ["created_at"],
        )

    if "specialty_requests" not in existing:
        op.create_table(
            "specialty_requests",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("fio", sa.String(length=100), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("phone", sa.String(length=20), nullable=False),
            sa.Column("date", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "test_result",
                sa.String(length=10),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_specialty_requests_phone", "specialty_requests", ["phone"])
        op.create_index("ix_specialty_requests_email", "specialty_requests", ["email"])
        op.create_index(
            "ix_specialty_requests_created_at",
            "specialty_requests",
            ["created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_specialty_requests_created_at", table_name="specialty_requests")
    op.drop_index("ix_specialty_requests_email", table_name="specialty_requests")
    op.drop_index("ix_specialty_requests_phone", table_name="specialty_requests")
    op.drop_table("specialty_requests")

    op.drop_index("ix_open_day_applications_created_at", table_name="open_day_applications")
    op.drop_index("ix_open_day_applications_email", table_name="open_day_applications")
    op.drop_index("ix_open_day_applications_phone", table_name="open_day_applications")
    op.drop_table("open_day_applications")
