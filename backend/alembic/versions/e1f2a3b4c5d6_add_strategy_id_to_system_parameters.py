"""add strategy_id to system_parameters

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-03-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. strategy_id 컬럼 추가
    op.add_column(
        'system_parameters',
        sa.Column('strategy_id', sa.Integer(), sa.ForeignKey('strategies.id', ondelete='CASCADE'), nullable=True),
    )

    # 2. 기존 unique(key) 제약 삭제
    op.drop_constraint('system_parameters_key_key', 'system_parameters', type_='unique')

    # 3. 새 unique(key, strategy_id) 제약 추가
    op.create_unique_constraint(
        'uq_system_parameters_key_strategy', 'system_parameters', ['key', 'strategy_id']
    )

    # 4. key 인덱스 추가
    op.create_index('ix_system_parameters_key', 'system_parameters', ['key'])


def downgrade() -> None:
    op.drop_index('ix_system_parameters_key', table_name='system_parameters')
    op.drop_constraint('uq_system_parameters_key_strategy', 'system_parameters', type_='unique')
    op.create_unique_constraint('system_parameters_key_key', 'system_parameters', ['key'])
    op.drop_column('system_parameters', 'strategy_id')
