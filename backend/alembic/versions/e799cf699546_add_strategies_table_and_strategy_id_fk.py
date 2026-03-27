"""add strategies table and strategy_id FK to related tables

Revision ID: e799cf699546
Revises: bc5cbf66d29a
Create Date: 2026-03-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e799cf699546"
down_revision: Union[str, None] = "bc5cbf66d29a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. strategies 테이블 생성
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("initial_capital", sa.Numeric(20, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # 2. default 전략 삽입
    op.execute(
        "INSERT INTO strategies (name, description, initial_capital) "
        "VALUES ('default', '기본 전략', 10000000)"
    )

    # 3. 각 테이블에 strategy_id 컬럼 추가 (nullable로 먼저)
    for table in ["assets", "decision_histories", "order_histories", "prompt_templates", "target_stocks"]:
        op.add_column(table, sa.Column("strategy_id", sa.Integer(), nullable=True))

    # 4. 기존 데이터에 default 전략 ID 할당
    op.execute("UPDATE assets SET strategy_id = (SELECT id FROM strategies WHERE name = 'default')")
    op.execute("UPDATE decision_histories SET strategy_id = (SELECT id FROM strategies WHERE name = 'default')")
    op.execute("UPDATE order_histories SET strategy_id = (SELECT id FROM strategies WHERE name = 'default')")
    op.execute("UPDATE prompt_templates SET strategy_id = (SELECT id FROM strategies WHERE name = 'default')")
    op.execute("UPDATE target_stocks SET strategy_id = (SELECT id FROM strategies WHERE name = 'default')")

    # 5. NOT NULL 제약 추가
    for table in ["assets", "decision_histories", "order_histories", "prompt_templates", "target_stocks"]:
        op.alter_column(table, "strategy_id", nullable=False)

    # 6. FK 추가
    op.create_foreign_key("fk_assets_strategy_id", "assets", "strategies", ["strategy_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_decision_histories_strategy_id", "decision_histories", "strategies", ["strategy_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_order_histories_strategy_id", "order_histories", "strategies", ["strategy_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_prompt_templates_strategy_id", "prompt_templates", "strategies", ["strategy_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_target_stocks_strategy_id", "target_stocks", "strategies", ["strategy_id"], ["id"], ondelete="RESTRICT")

    # 7. 인덱스 추가
    op.create_index("ix_assets_strategy_id", "assets", ["strategy_id"])
    op.create_unique_constraint("uq_assets_strategy_stock", "assets", ["strategy_id", "stock_code"])

    op.create_index("ix_decision_histories_strategy_id_created_at", "decision_histories", ["strategy_id", "created_at"])

    op.create_index("ix_order_histories_strategy_id_created_at", "order_histories", ["strategy_id", "created_at"])
    op.create_index("ix_order_histories_strategy_id_stock_code_created_at", "order_histories", ["strategy_id", "stock_code", "created_at"])

    op.create_index("ix_prompt_templates_strategy_id_prompt_type", "prompt_templates", ["strategy_id", "prompt_type"])

    # target_stocks: 기존 unique(stock_code) 제거 → unique(strategy_id, stock_code)로 대체
    op.drop_constraint("target_stocks_stock_code_key", "target_stocks", type_="unique")
    op.create_unique_constraint("uq_target_stocks_strategy_stock", "target_stocks", ["strategy_id", "stock_code"])
    op.create_index("ix_target_stocks_strategy_id_is_active", "target_stocks", ["strategy_id", "is_active"])


def downgrade() -> None:
    # 인덱스/제약 삭제
    op.drop_index("ix_target_stocks_strategy_id_is_active", "target_stocks")
    op.drop_constraint("uq_target_stocks_strategy_stock", "target_stocks", type_="unique")
    op.create_unique_constraint("target_stocks_stock_code_key", "target_stocks", ["stock_code"])

    op.drop_index("ix_prompt_templates_strategy_id_prompt_type", "prompt_templates")

    op.drop_index("ix_order_histories_strategy_id_stock_code_created_at", "order_histories")
    op.drop_index("ix_order_histories_strategy_id_created_at", "order_histories")

    op.drop_index("ix_decision_histories_strategy_id_created_at", "decision_histories")

    op.drop_constraint("uq_assets_strategy_stock", "assets", type_="unique")
    op.drop_index("ix_assets_strategy_id", "assets")

    # FK 삭제
    op.drop_constraint("fk_target_stocks_strategy_id", "target_stocks", type_="foreignkey")
    op.drop_constraint("fk_prompt_templates_strategy_id", "prompt_templates", type_="foreignkey")
    op.drop_constraint("fk_order_histories_strategy_id", "order_histories", type_="foreignkey")
    op.drop_constraint("fk_decision_histories_strategy_id", "decision_histories", type_="foreignkey")
    op.drop_constraint("fk_assets_strategy_id", "assets", type_="foreignkey")

    # 컬럼 삭제
    for table in ["assets", "decision_histories", "order_histories", "prompt_templates", "target_stocks"]:
        op.drop_column(table, "strategy_id")

    # strategies 테이블 삭제
    op.drop_table("strategies")
