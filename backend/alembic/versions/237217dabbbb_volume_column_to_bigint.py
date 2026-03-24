"""volume column to bigint

Revision ID: 237217dabbbb
Revises: 0b2cdcfca762
Create Date: 2026-03-24 09:13:25.163878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '237217dabbbb'
down_revision: Union[str, Sequence[str], None] = '0b2cdcfca762'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "minute_candles",
        "volume",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "minute_candles",
        "volume",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=True,
    )
