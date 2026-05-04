"""add_status_field_to_applications

Revision ID: f7e8d9c0b1a2
Revises: c8f3a2b1d9e5
Create Date: 2026-05-02 12:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7e8d9c0b1a2"
down_revision: Union[str, None] = "c8f3a2b1d9e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _index_exists(bind, table: str, index_name: str) -> bool:
    insp = sa.inspect(bind)
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()

    if not _column_exists(bind, "open_day_applications", "status"):
        op.add_column(
            "open_day_applications",
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="new",
            ),
        )
    if not _index_exists(bind, "open_day_applications", "ix_open_day_applications_status"):
        op.create_index(
            "ix_open_day_applications_status",
            "open_day_applications",
            ["status"],
        )

    if not _column_exists(bind, "specialty_requests", "status"):
        op.add_column(
            "specialty_requests",
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="new",
            ),
        )
    if not _index_exists(bind, "specialty_requests", "ix_specialty_requests_status"):
        op.create_index(
            "ix_specialty_requests_status",
            "specialty_requests",
            ["status"],
        )


def downgrade() -> None:
    op.drop_index("ix_specialty_requests_status", table_name="specialty_requests")
    op.drop_column("specialty_requests", "status")

    op.drop_index("ix_open_day_applications_status", table_name="open_day_applications")
    op.drop_column("open_day_applications", "status")
