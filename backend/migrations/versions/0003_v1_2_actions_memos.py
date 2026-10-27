"""v1.2 product actions and review memos

상품 개선 조치 기록, 리뷰 내부 메모·처리 상태

서버 시작(create_all)이 먼저 만들었을 수 있으므로 이미 있는 테이블은 건너뜀 (0001·0002 와 같은 방식)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKIPPED: set[str] = set()


def _create(name: str, *columns, **kw) -> None:
    if name in sa.inspect(op.get_bind()).get_table_names():
        _SKIPPED.add(name)
        return
    op.create_table(name, *columns, **kw)


def _index(table: str, name: str, columns: list[str], unique: bool = False) -> None:
    if table not in _SKIPPED:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _create('product_actions',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('product_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('action_date', sa.Date(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('issue_type', sa.Enum('PRODUCT', 'DELIVERY', 'PACKAGING', 'ETC', name='action_issue_type'), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('product_actions', 'ix_product_actions_product_date', ['product_id', 'action_date'], unique=False)

    _create('review_memos',
    sa.Column('review_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('status', sa.Enum('TODO', 'IN_PROGRESS', 'DONE', name='memo_status'), server_default='TODO', nullable=False),
    sa.Column('memo', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('review_id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )


def downgrade() -> None:
    op.drop_table('review_memos')
    op.drop_index('ix_product_actions_product_date', table_name='product_actions')

    op.drop_table('product_actions')
