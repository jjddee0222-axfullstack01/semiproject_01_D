"""baseline v1.0.0 tables (15)

v1.0.0 의 15개 테이블

서버(create_all)가 이미 만든 DB 에서도 그대로 실행할 수 있도록, 이미 있는 테이블과 그 인덱스는 건너뜀
→ 기존 DB 도 'python -m alembic upgrade head' 한 번이면 버전 기록(alembic_version)이 생김

Revision ID: 0001
Revises: 
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── 이미 있는 테이블은 건너뛰기 (create_all 로 만든 기존 DB 호환)
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
    _create('ingest_logs',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('batch_name', sa.String(length=255), nullable=False),
    sa.Column('total_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('duplicate_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('missing_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('run_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _create('keywords',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('word', sa.String(length=100), nullable=False),
    sa.Column('polarity', sa.Enum('POS', 'NEG', 'NEU', name='keyword_polarity'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('word'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('keywords', 'ix_keywords_polarity', ['polarity'], unique=False)

    _create('users',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('mall_name', sa.String(length=100), nullable=False),
    sa.Column('mall_platform', sa.Enum('NAVER', 'COUPANG', 'OWN', 'ETC', name='mall_platform'), nullable=False),
    sa.Column('business_number', mysql.CHAR(length=10).with_variant(sa.String(length=10), 'sqlite'), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'WITHDRAWN', name='user_status'), server_default='ACTIVE', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('withdrawn_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_number'),
    sa.UniqueConstraint('email'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _create('feedbacks',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('complaint', sa.Text(), nullable=False),
    sa.Column('suggestion', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _create('products',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('seller_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('description_embedding', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['seller_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('products', 'ix_products_seller_category', ['seller_id', 'category'], unique=False)

    _create('risk_keywords',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('seller_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('word', sa.String(length=100), nullable=False),
    sa.Column('weight', sa.SmallInteger().with_variant(mysql.TINYINT(unsigned=True), 'mariadb').with_variant(mysql.TINYINT(unsigned=True), 'mysql'), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['seller_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('seller_id', 'word', name='uq_risk_keywords_seller_word'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _create('sessions',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('session_token_hash', mysql.CHAR(length=64).with_variant(sa.String(length=64), 'sqlite'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_token_hash'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('sessions', 'ix_sessions_expires_at', ['expires_at'], unique=False)
    _index('sessions', 'ix_sessions_user_id', ['user_id'], unique=False)

    _create('shop_monthly_stats',
    sa.Column('seller_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('visitors', sa.Integer(), server_default='0', nullable=False),
    sa.Column('buyers', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['seller_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('seller_id', 'month'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _create('product_monthly_stats',
    sa.Column('product_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('buyers', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('product_id', 'month'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _create('reviews',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('product_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('reviewer_name', sa.String(length=50), nullable=True),
    sa.Column('rating', sa.SmallInteger().with_variant(mysql.TINYINT(unsigned=True), 'mariadb').with_variant(mysql.TINYINT(unsigned=True), 'mysql'), nullable=False),
    sa.Column('content_raw', sa.Text(), nullable=False),
    sa.Column('content_clean', sa.Text(), nullable=True),
    sa.Column('content_embedding', sa.JSON(), nullable=True),
    sa.Column('reviewed_at', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('VISIBLE', 'BLINDED', name='review_status'), server_default='VISIBLE', nullable=False),
    sa.Column('blind_reason', sa.String(length=500), nullable=True),
    sa.Column('blinded_by', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('blinded_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint("status <> 'BLINDED' OR blind_reason IS NOT NULL", name='ck_reviews_blind_reason'),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_reviews_rating'),
    sa.ForeignKeyConstraint(['blinded_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('reviews', 'ix_reviews_product_status_reviewed', ['product_id', 'status', 'reviewed_at'], unique=False)

    _create('reply_suggestions',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('review_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('draft', sa.Text(), nullable=False),
    sa.Column('llm_model', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('reply_suggestions', 'ix_reply_suggestions_review_created', ['review_id', 'created_at'], unique=False)

    _create('review_analysis',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('review_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('sentiment', sa.Enum('POS', 'NEG', 'NEU', name='sentiment'), nullable=False),
    sa.Column('sentiment_score', sa.Float(), nullable=True),
    sa.Column('severity', sa.SmallInteger().with_variant(mysql.TINYINT(unsigned=True), 'mariadb').with_variant(mysql.TINYINT(unsigned=True), 'mysql'), server_default='0', nullable=False),
    sa.Column('issue_type', sa.Enum('PRODUCT', 'DELIVERY', 'PACKAGING', 'ETC', name='issue_type'), nullable=True),
    sa.Column('model_version', sa.String(length=50), nullable=False),
    sa.Column('analyzed_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.CheckConstraint('severity BETWEEN 0 AND 3', name='ck_review_analysis_severity'),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('review_id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('review_analysis', 'ix_review_analysis_issue_severity', ['issue_type', 'severity'], unique=False)

    _create('review_blind_logs',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('review_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('actor_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('action', sa.Enum('BLIND', 'RESTORE', name='blind_action'), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('review_blind_logs', 'ix_review_blind_logs_review_created', ['review_id', 'created_at'], unique=False)

    _create('review_keywords',
    sa.Column('review_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('keyword_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['keyword_id'], ['keywords.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('review_id', 'keyword_id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('review_keywords', 'ix_review_keywords_keyword', ['keyword_id'], unique=False)

    _create('review_replies',
    sa.Column('id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('review_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('parent_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('author_id', sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mariadb').with_variant(mysql.BIGINT(unsigned=True), 'mysql').with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_id'], ['review_replies.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_unicode_ci',
    mariadb_engine='InnoDB',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci',
    mysql_engine='InnoDB'
    )
    _index('review_replies', 'ix_review_replies_review_parent', ['review_id', 'parent_id'], unique=False)



def downgrade() -> None:
    op.drop_index('ix_review_replies_review_parent', table_name='review_replies')

    op.drop_table('review_replies')
    op.drop_index('ix_review_keywords_keyword', table_name='review_keywords')

    op.drop_table('review_keywords')
    op.drop_index('ix_review_blind_logs_review_created', table_name='review_blind_logs')

    op.drop_table('review_blind_logs')
    op.drop_index('ix_review_analysis_issue_severity', table_name='review_analysis')

    op.drop_table('review_analysis')
    op.drop_index('ix_reply_suggestions_review_created', table_name='reply_suggestions')

    op.drop_table('reply_suggestions')
    op.drop_index('ix_reviews_product_status_reviewed', table_name='reviews')

    op.drop_table('reviews')
    op.drop_table('product_monthly_stats')
    op.drop_table('shop_monthly_stats')
    op.drop_index('ix_sessions_user_id', table_name='sessions')
    op.drop_index('ix_sessions_expires_at', table_name='sessions')

    op.drop_table('sessions')
    op.drop_table('risk_keywords')
    op.drop_index('ix_products_seller_category', table_name='products')

    op.drop_table('products')
    op.drop_table('feedbacks')
    op.drop_table('users')
    op.drop_index('ix_keywords_polarity', table_name='keywords')

    op.drop_table('keywords')
    op.drop_table('ingest_logs')
