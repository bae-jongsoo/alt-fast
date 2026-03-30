"""add is_processed to dart_disclosures

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-03-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'dart_disclosures',
        sa.Column('is_processed', sa.Boolean(), server_default='false', nullable=False),
    )
    op.create_index(
        'ix_dart_disclosures_is_processed',
        'dart_disclosures',
        ['is_processed'],
    )


def downgrade() -> None:
    op.drop_index('ix_dart_disclosures_is_processed', table_name='dart_disclosures')
    op.drop_column('dart_disclosures', 'is_processed')
