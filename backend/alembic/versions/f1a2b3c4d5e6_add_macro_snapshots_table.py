"""add macro_snapshots table

Revision ID: f1a2b3c4d5e6
Revises: e799cf699546
Create Date: 2026-03-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e799cf699546'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('macro_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        # 미국 지수
        sa.Column('sp500_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('sp500_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('nasdaq_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('nasdaq_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('dow_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('dow_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('russell2000_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('russell2000_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        # 변동성
        sa.Column('vix', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('vix_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        # 미국 금리
        sa.Column('us_13w_tbill', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('us_5y_treasury', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('us_10y_treasury', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('us_30y_treasury', sa.Numeric(precision=20, scale=6), nullable=True),
        # 환율
        sa.Column('usd_krw', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('usd_krw_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('usd_cny', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('usd_cny_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('usd_jpy', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('usd_jpy_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('dxy', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('dxy_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        # 원자재
        sa.Column('gold', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('gold_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('wti', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('wti_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('copper', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('copper_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        # 아시아 지수
        sa.Column('nikkei_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('nikkei_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('hang_seng_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('hang_seng_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('shanghai_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('shanghai_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        # 반도체/한국
        sa.Column('sox_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('sox_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('ewy_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('ewy_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('kr_bond_10y_close', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('kr_bond_10y_change_pct', sa.Numeric(precision=20, scale=6), nullable=True),
        # 한국 기준금리
        sa.Column('kr_base_rate', sa.Numeric(precision=20, scale=6), nullable=True),
        # 기타
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_date'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('macro_snapshots')
