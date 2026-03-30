"""add trading_events table

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-03-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('trading_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('stock_code', sa.String(length=32), nullable=False),
        sa.Column('stock_name', sa.String(length=50), nullable=False),
        sa.Column('event_data', sa.JSON(), nullable=True),
        sa.Column('confidence_hint', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('strategy_id', sa.Integer(), sa.ForeignKey('strategies.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decision_history_id', sa.Integer(), sa.ForeignKey('decision_histories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('detected_at', sa.DateTime(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trading_events_event_type', 'trading_events', ['event_type'])
    op.create_index('ix_trading_events_stock_code', 'trading_events', ['stock_code'])
    op.create_index('ix_trading_events_status', 'trading_events', ['status'])
    op.create_index('ix_trading_events_detected_at', 'trading_events', ['detected_at'])
    op.create_index('ix_trading_events_stock_code_event_type_detected_at', 'trading_events', ['stock_code', 'event_type', 'detected_at'])


def downgrade() -> None:
    op.drop_index('ix_trading_events_stock_code_event_type_detected_at', table_name='trading_events')
    op.drop_index('ix_trading_events_detected_at', table_name='trading_events')
    op.drop_index('ix_trading_events_status', table_name='trading_events')
    op.drop_index('ix_trading_events_stock_code', table_name='trading_events')
    op.drop_index('ix_trading_events_event_type', table_name='trading_events')
    op.drop_table('trading_events')
