"""v1.1 notification settings and reply templates

위험 리뷰 메일 알림 설정, 셀러 답글 템플릿

서버 시작(create_all)이 먼저 만들었을 수 있으므로 이미 있는 테이블은 건너뜀 (0001 과 같은 방식)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create(name: str, *columns, **kw) -> None:
    if name not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(name, *columns, **kw)


def upgrade() -> None:
    _create('notification_settings',
    sa.Column('seller_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('risk_email', sa.Boolean(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['seller_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('seller_id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _create('reply_templates',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('seller_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('sentiment', sa.Enum('POS', 'NEG', 'NEU', name='template_sentiment'), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['seller_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('seller_id', 'sentiment', name='uq_reply_templates_seller_sentiment'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )


def downgrade() -> None:
    op.drop_table('reply_templates')
    op.drop_table('notification_settings')
