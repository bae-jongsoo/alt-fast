"""add news_clusters table and cluster_id to news

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-03-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create news_clusters table
    op.create_table('news_clusters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stock_code', sa.String(length=32), nullable=False),
        sa.Column('stock_name', sa.String(length=50), nullable=False),
        sa.Column('cluster_type', sa.String(length=20), nullable=False),
        sa.Column('keyword', sa.String(length=100), nullable=True),
        sa.Column('news_count', sa.Integer(), nullable=False),
        sa.Column('first_news_at', sa.DateTime(), nullable=False),
        sa.Column('last_news_at', sa.DateTime(), nullable=False),
        sa.Column('is_processed', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_news_clusters_stock_code', 'news_clusters', ['stock_code'])
    op.create_index('ix_news_clusters_is_processed', 'news_clusters', ['is_processed'])
    op.create_index('ix_news_clusters_created_at', 'news_clusters', ['created_at'])

    # Add cluster_id FK to news table
    op.add_column('news',
        sa.Column('cluster_id', sa.Integer(), sa.ForeignKey('news_clusters.id'), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('news', 'cluster_id')
    op.drop_index('ix_news_clusters_created_at', table_name='news_clusters')
    op.drop_index('ix_news_clusters_is_processed', table_name='news_clusters')
    op.drop_index('ix_news_clusters_stock_code', table_name='news_clusters')
    op.drop_table('news_clusters')
