"""add event_id, target_return_pct, stop_pct, holding_days to order_histories

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-03-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('order_histories', sa.Column('event_id', sa.Integer(), sa.ForeignKey('trading_events.id', ondelete='SET NULL'), nullable=True))
    op.add_column('order_histories', sa.Column('target_return_pct', sa.Numeric(precision=10, scale=4), nullable=True))
    op.add_column('order_histories', sa.Column('stop_pct', sa.Numeric(precision=10, scale=4), nullable=True))
    op.add_column('order_histories', sa.Column('holding_days', sa.Integer(), nullable=True))
    op.create_index('ix_order_histories_event_id', 'order_histories', ['event_id'])


def downgrade() -> None:
    op.drop_index('ix_order_histories_event_id', table_name='order_histories')
    op.drop_column('order_histories', 'holding_days')
    op.drop_column('order_histories', 'stop_pct')
    op.drop_column('order_histories', 'target_return_pct')
    op.drop_column('order_histories', 'event_id')
