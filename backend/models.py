"""
PIN POINT REVIEW - SQLAlchemy 2.0 ORM 모델

기준: docs/04_database_design.md 의 ERD "Pinpoint Review ERD (MariaDB)" — 12개 테이블
      (정책·제약은 docs/02_requirements.md, 05_api_spec.md, 06_architecture.md 참고)

  USERS ─┬─< SESSIONS                      PRODUCTS ─< REVIEWS ─┬─< REVIEW_BLIND_LOGS >o─ USERS(actor)
         ├─< PRODUCTS                                          ├─< REVIEW_REPLIES    >o─ USERS(author)
         └─< RISK_KEYWORDS                                     ├─< REPLY_SUGGESTIONS
                                                               ├── REVIEW_ANALYSIS  (1:1)
  INGEST_LOGS (독립)                    KEYWORDS ─< REVIEW_KEYWORDS >─┘

ERD에 없는 것 중 이 파일에서 추가한 것 (문서 정책 근거)
  - CHECK  : rating 1~5, severity 0~3, 블라인드 시 blind_reason 필수
  - UNIQUE : risk_keywords(seller_id, word)  ← API "409(중복)"
  - INDEX  : 상품·기간 집계, 위험 리뷰 정렬, 세션 만료 정리용
  - 보조 테이블 3개 (현재 화면용, 맨 아래): shop_monthly_stats, product_monthly_stats, feedbacks
  - v1.1 추가 2개 (맨 아래): notification_settings(위험 리뷰 메일 알림), reply_templates(셀러 답글 템플릿)
    → 마이그레이션: migrations/versions/0002_*.py
  - v1.2 추가 2개 (맨 아래): product_actions(상품 개선 조치 기록), review_memos(리뷰 내부 메모·처리 상태)
    → 마이그레이션: migrations/versions/0003_*.py
"""
from __future__ import annotations

import enum
import hashlib
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, Enum, Float,
                        ForeignKey, Index, Integer, SmallInteger, String, Text,
                        UniqueConstraint, func, select)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, backref, mapped_column, relationship

# ──────────────────────────────────────────────
# 공통 타입 / 옵션
# ──────────────────────────────────────────────
# ID: ERD의 BIGINT → DDL 기준 BIGINT UNSIGNED AUTO_INCREMENT (06_architecture 7장-2)
#     SQLite(개발용)는 INTEGER PRIMARY KEY 여야 자동 증가하므로 INTEGER 로 대체
ID = (BigInteger()
      .with_variant(mysql.BIGINT(unsigned=True), "mysql", "mariadb")
      .with_variant(Integer(), "sqlite"))

# ERD의 TINYINT (rating, weight, severity)
TinyInt = SmallInteger().with_variant(mysql.TINYINT(unsigned=True), "mysql", "mariadb")

# 테이블 옵션: InnoDB + utf8mb4 (한글·이모지 리뷰)
#  접속 URL이 mariadb+... 이면 mariadb_*, mysql+... 이면 mysql_* 옵션이 적용되므로 둘 다 지정
MYSQL_OPTS = {
    f"{prefix}_{key}": value
    for prefix in ("mysql", "mariadb")
    for key, value in {"engine": "InnoDB", "charset": "utf8mb4", "collate": "utf8mb4_unicode_ci"}.items()
}


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """DB에는 Enum 값(문자열)을 그대로 저장 → MariaDB ENUM('A','B',…)"""
    return Enum(enum_cls, name=name, native_enum=True, validate_strings=True,
                values_callable=lambda e: [m.value for m in e])


def _char(length: int):
    """ERD의 CHAR(n) — MariaDB는 CHAR, SQLite는 VARCHAR"""
    return mysql.CHAR(length).with_variant(String(length), "sqlite")


def _now():
    return mapped_column(DateTime, server_default=func.now(), nullable=False)


class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────
# Enum (ERD 표기 그대로)
# ──────────────────────────────────────────────
class MallPlatform(str, enum.Enum):
    NAVER = "NAVER"            # 네이버 스마트스토어
    COUPANG = "COUPANG"
    OWN = "OWN"                # 자사몰
    ETC = "ETC"


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"    # 사용하지 않음: 탈퇴는 하드 삭제로 변경 (D5, auth.delete_account). 기존 데이터 호환용으로 남김


class ReviewStatus(str, enum.Enum):
    VISIBLE = "VISIBLE"
    BLINDED = "BLINDED"        # D2: 블라인드 = 소프트 삭제


class Polarity(str, enum.Enum):
    """keywords.polarity / review_analysis.sentiment 공통"""
    POS = "POS"
    NEG = "NEG"
    NEU = "NEU"


class IssueType(str, enum.Enum):
    PRODUCT = "PRODUCT"
    DELIVERY = "DELIVERY"
    PACKAGING = "PACKAGING"
    ETC = "ETC"


class MemoStatus(str, enum.Enum):
    """v1.2 리뷰 내부 처리 상태 (셀러 팀 안에서만 쓰는 값, 쇼핑몰에는 보이지 않음)"""
    TODO = "TODO"                  # 확인 필요
    IN_PROGRESS = "IN_PROGRESS"    # 처리 중
    DONE = "DONE"                  # 처리 완료


class BlindAction(str, enum.Enum):
    BLIND = "BLIND"
    RESTORE = "RESTORE"        # 블라인드 해제(복구)


# ══════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════
class User(Base):
    __tablename__ = "users"
    __table_args__ = (MYSQL_OPTS,)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    mall_name: Mapped[str] = mapped_column(String(100), nullable=False)                  # 쇼핑몰명
    mall_platform: Mapped[MallPlatform] = mapped_column(_enum(MallPlatform, "mall_platform"), nullable=False)
    business_number: Mapped[str] = mapped_column(_char(10), unique=True, nullable=False)  # 사업자등록번호 (숫자 10자리)
    status: Mapped[UserStatus] = mapped_column(_enum(UserStatus, "user_status"),
                                               default=UserStatus.ACTIVE,
                                               server_default=UserStatus.ACTIVE.value, nullable=False)
    created_at: Mapped[datetime] = _now()
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    sessions: Mapped[list[UserSession]] = relationship(back_populates="user", cascade="all, delete-orphan",
                                                       passive_deletes=True)
    products: Mapped[list[Product]] = relationship(back_populates="seller", passive_deletes=True)
    risk_keywords: Mapped[list[RiskKeyword]] = relationship(back_populates="seller", cascade="all, delete-orphan",
                                                            passive_deletes=True)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} status={self.status.value}>"


# ══════════════════════════════════════════════
# SESSIONS — 쿠키에는 원본 토큰, DB에는 SHA-256 해시만 저장
# ══════════════════════════════════════════════
class UserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_expires_at", "expires_at"),                                   # 만료 세션 정리
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash: Mapped[str] = mapped_column(_char(64), unique=True, nullable=False)  # SHA-256 해시
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")

    @staticmethod
    def hash_token(token: str) -> str:
        """쿠키의 session_id 값 → DB 저장/조회용 해시 (64자 hex)"""
        return hashlib.sha256(token.encode()).hexdigest()


# ══════════════════════════════════════════════
# PRODUCTS — 소유권: products.seller_id = 요청자 (D3)
# ══════════════════════════════════════════════
class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_seller_category", "seller_id", "category"),                   # ?q=&category= 검색
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    description_embedding: Mapped[Optional[list[float]]] = mapped_column(JSON)            # D6
    created_at: Mapped[datetime] = _now()

    seller: Mapped[User] = relationship(back_populates="products")
    reviews: Mapped[list[Review]] = relationship(back_populates="product", cascade="all, delete-orphan",
                                                 passive_deletes=True)


# ══════════════════════════════════════════════
# RISK_KEYWORDS — 셀러별 위험 키워드 (불호 리뷰 상단 노출 기준)
# ══════════════════════════════════════════════
class RiskKeyword(Base):
    __tablename__ = "risk_keywords"
    __table_args__ = (
        UniqueConstraint("seller_id", "word", name="uq_risk_keywords_seller_word"),      # 409(중복)
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    word: Mapped[str] = mapped_column(String(100), nullable=False)
    weight: Mapped[int] = mapped_column(TinyInt, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = _now()

    seller: Mapped[User] = relationship(back_populates="risk_keywords")


# ══════════════════════════════════════════════
# INGEST_LOGS — 데이터셋 적재 이력 (중복·결측 건수)
# ══════════════════════════════════════════════
class IngestLog(Base):
    __tablename__ = "ingest_logs"
    __table_args__ = (MYSQL_OPTS,)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    batch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    missing_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    run_at: Mapped[datetime] = _now()


# ══════════════════════════════════════════════
# REVIEWS — 수집 데이터 (사용자가 작성·수정하지 않음, D1)
# ══════════════════════════════════════════════
class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating"),
        CheckConstraint("status <> 'BLINDED' OR blind_reason IS NOT NULL",
                        name="ck_reviews_blind_reason"),                                 # 블라인드 시 사유 필수
        Index("ix_reviews_product_status_reviewed", "product_id", "status", "reviewed_at"),  # 상품·기간 집계
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    reviewer_name: Mapped[Optional[str]] = mapped_column(String(50))                      # 마스킹된 표시명
    rating: Mapped[int] = mapped_column(TinyInt, nullable=False)
    content_raw: Mapped[str] = mapped_column(Text, nullable=False)                        # 원문
    content_clean: Mapped[Optional[str]] = mapped_column(Text)                            # 정제본 (US-10 분리 보존)
    content_embedding: Mapped[Optional[list[float]]] = mapped_column(JSON)                # D6
    reviewed_at: Mapped[date] = mapped_column(Date, nullable=False)                       # 고객 작성일
    status: Mapped[ReviewStatus] = mapped_column(_enum(ReviewStatus, "review_status"),
                                                 default=ReviewStatus.VISIBLE,
                                                 server_default=ReviewStatus.VISIBLE.value, nullable=False)
    blind_reason: Mapped[Optional[str]] = mapped_column(String(500))
    blinded_by: Mapped[Optional[int]] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))  # D5 익명화
    blinded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _now()                                                 # 적재 시각

    product: Mapped[Product] = relationship(back_populates="reviews")
    blinder: Mapped[Optional[User]] = relationship(foreign_keys=[blinded_by])
    analysis: Mapped[Optional[ReviewAnalysis]] = relationship(back_populates="review", uselist=False,
                                                              cascade="all, delete-orphan", passive_deletes=True)
    keyword_links: Mapped[list[ReviewKeyword]] = relationship(back_populates="review", cascade="all, delete-orphan",
                                                              passive_deletes=True)
    blind_logs: Mapped[list[ReviewBlindLog]] = relationship(back_populates="review", cascade="all, delete-orphan",
                                                            passive_deletes=True,
                                                            order_by="ReviewBlindLog.created_at")
    replies: Mapped[list[ReviewReply]] = relationship(back_populates="review", cascade="all, delete-orphan",
                                                      passive_deletes=True, order_by="ReviewReply.created_at")
    reply_suggestions: Mapped[list[ReplySuggestion]] = relationship(back_populates="review",
                                                                    cascade="all, delete-orphan",
                                                                    passive_deletes=True)

    @property
    def is_blinded(self) -> bool:
        return self.status == ReviewStatus.BLINDED

    @property
    def root_replies(self) -> list[ReviewReply]:
        """답글 트리의 최상위 답글 (하위 답글은 reply.children)"""
        return [r for r in self.replies if r.parent_id is None]


def visible_reviews():
    """통계·위험 리뷰·키워드·CSV 집계는 반드시 이 쿼리에서 시작
    (06_architecture 7장-1: status='VISIBLE' 조건을 한 곳에서 관리)

    예) session.scalars(visible_reviews().where(Review.product_id == 1)).all()
    """
    return select(Review).where(Review.status == ReviewStatus.VISIBLE)


# ══════════════════════════════════════════════
# REVIEW_ANALYSIS — 리뷰와 1:1 (review_id FK/UK)
# ══════════════════════════════════════════════
class ReviewAnalysis(Base):
    __tablename__ = "review_analysis"
    __table_args__ = (
        CheckConstraint("severity BETWEEN 0 AND 3", name="ck_review_analysis_severity"),
        Index("ix_review_analysis_issue_severity", "issue_type", "severity"),            # 위험 리뷰 심각도순
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ID, ForeignKey("reviews.id", ondelete="CASCADE"),
                                           unique=True, nullable=False)
    sentiment: Mapped[Polarity] = mapped_column(_enum(Polarity, "sentiment"), nullable=False)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float)
    severity: Mapped[int] = mapped_column(TinyInt, default=0, server_default="0", nullable=False)  # 0~3
    issue_type: Mapped[Optional[IssueType]] = mapped_column(_enum(IssueType, "issue_type"))
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)                # 7장-6 재분석 범위 식별
    analyzed_at: Mapped[datetime] = _now()

    review: Mapped[Review] = relationship(back_populates="analysis")


# ══════════════════════════════════════════════
# KEYWORDS / REVIEW_KEYWORDS (N:M)
# ══════════════════════════════════════════════
class Keyword(Base):
    __tablename__ = "keywords"
    __table_args__ = (
        Index("ix_keywords_polarity", "polarity"),                                       # TOP 10 ?polarity=
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    polarity: Mapped[Polarity] = mapped_column(_enum(Polarity, "keyword_polarity"), nullable=False)

    review_links: Mapped[list[ReviewKeyword]] = relationship(back_populates="keyword", passive_deletes=True)


class ReviewKeyword(Base):
    __tablename__ = "review_keywords"
    __table_args__ = (
        Index("ix_review_keywords_keyword", "keyword_id"),                               # 키워드별 빈도 집계
        MYSQL_OPTS,
    )

    review_id: Mapped[int] = mapped_column(ID, ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ID, ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True)
    score: Mapped[Optional[float]] = mapped_column(Float)                                 # 리뷰 내 키워드 중요도

    review: Mapped[Review] = relationship(back_populates="keyword_links")
    keyword: Mapped[Keyword] = relationship(back_populates="review_links")


# ══════════════════════════════════════════════
# REVIEW_BLIND_LOGS — 블라인드·복구 이력
# ══════════════════════════════════════════════
class ReviewBlindLog(Base):
    __tablename__ = "review_blind_logs"
    __table_args__ = (
        Index("ix_review_blind_logs_review_created", "review_id", "created_at"),
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ID, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))  # D5 익명화
    action: Mapped[BlindAction] = mapped_column(_enum(BlindAction, "blind_action"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500))                            # BLIND 일 때 필수(API 검증)
    created_at: Mapped[datetime] = _now()

    review: Mapped[Review] = relationship(back_populates="blind_logs")
    actor: Mapped[Optional[User]] = relationship()


# ══════════════════════════════════════════════
# REVIEW_REPLIES — CS 답글 트리 (상위 삭제 시 하위도 삭제, D4)
# ══════════════════════════════════════════════
class ReviewReply(Base):
    __tablename__ = "review_replies"
    __table_args__ = (
        Index("ix_review_replies_review_parent", "review_id", "parent_id"),
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ID, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ID, ForeignKey("review_replies.id", ondelete="CASCADE"))
    author_id: Mapped[Optional[int]] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))  # D5 익명화
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)

    review: Mapped[Review] = relationship(back_populates="replies")
    author: Mapped[Optional[User]] = relationship()
    parent: Mapped[Optional[ReviewReply]] = relationship(back_populates="children", remote_side=[id])
    children: Mapped[list[ReviewReply]] = relationship(back_populates="parent", cascade="all, delete-orphan",
                                                       passive_deletes=True, order_by="ReviewReply.created_at")


# ══════════════════════════════════════════════
# REPLY_SUGGESTIONS — LLM 사과 답글 초안 (Could)
# ══════════════════════════════════════════════
class ReplySuggestion(Base):
    __tablename__ = "reply_suggestions"
    __table_args__ = (
        Index("ix_reply_suggestions_review_created", "review_id", "created_at"),
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ID, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    draft: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = _now()

    review: Mapped[Review] = relationship(back_populates="reply_suggestions")


# ══════════════════════════════════════════════
# (보조) 현재 화면에서 쓰는 테이블 — ERD 미포함, 팀 결정 필요
#   필요 없으면 이 아래를 지우면 됩니다.
# ══════════════════════════════════════════════
class ShopMonthlyStat(Base):
    """대시보드 '당월 사이트 방문자 수 / 당월 총 상품 구매자 수'"""
    __tablename__ = "shop_monthly_stats"
    __table_args__ = (MYSQL_OPTS,)

    seller_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)                           # 해당 월 1일
    visitors: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    buyers: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class ProductMonthlyStat(Base):
    """상품별 대시보드 '당월 구매자 수'"""
    __tablename__ = "product_monthly_stats"
    __table_args__ = (MYSQL_OPTS,)

    product_id: Mapped[int] = mapped_column(ID, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    buyers: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class Feedback(Base):
    """'의견 보내기' 화면"""
    __tablename__ = "feedbacks"
    __table_args__ = (MYSQL_OPTS,)

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    complaint: Mapped[str] = mapped_column(Text, nullable=False)                          # 불편 사항
    suggestion: Mapped[str] = mapped_column(Text, nullable=False)                         # 기타 제안 사항
    created_at: Mapped[datetime] = _now()


# ══════════════════════════════════════════════
# v1.1 — NOTIFICATION_SETTINGS / REPLY_TEMPLATES
# ══════════════════════════════════════════════
class NotificationSetting(Base):
    """셀러 알림 설정 (행이 없으면 모두 꺼짐). 탈퇴 시 users 삭제와 함께 CASCADE"""
    __tablename__ = "notification_settings"
    __table_args__ = (MYSQL_OPTS,)

    seller_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    risk_email: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)  # 업로드 후 위험 리뷰 메일
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(),
                                                 nullable=False)


class ReplyTemplate(Base):
    """셀러가 직접 쓴 답글 템플릿 — 감성(POS/NEU/NEG)마다 1개. 없으면 기본 템플릿(reply_drafts) 사용"""
    __tablename__ = "reply_templates"
    __table_args__ = (
        UniqueConstraint("seller_id", "sentiment", name="uq_reply_templates_seller_sentiment"),
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sentiment: Mapped[Polarity] = mapped_column(_enum(Polarity, "template_sentiment"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)                            # 최대 2,000자 (API 검증)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(),
                                                 nullable=False)


# ══════════════════════════════════════════════
# v1.2 — PRODUCT_ACTIONS / REVIEW_MEMOS
# ══════════════════════════════════════════════
class ProductAction(Base):
    """셀러가 상품에 한 개선 조치 (예: 2026-10-20 포장 박스 교체) → 조치 전후 리뷰 비교"""
    __tablename__ = "product_actions"
    __table_args__ = (
        Index("ix_product_actions_product_date", "product_id", "action_date"),
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ID, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    action_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    issue_type: Mapped[Optional[IssueType]] = mapped_column(_enum(IssueType, "action_issue_type"))  # 개선하려는 이슈 (없으면 전체)
    created_at: Mapped[datetime] = _now()

    product: Mapped[Product] = relationship()


class ReviewMemo(Base):
    """리뷰 1건당 내부 메모·처리 상태 1행 (담당자끼리 공유)"""
    __tablename__ = "review_memos"
    __table_args__ = (MYSQL_OPTS,)

    review_id: Mapped[int] = mapped_column(ID, ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[MemoStatus] = mapped_column(_enum(MemoStatus, "memo_status"), default=MemoStatus.TODO,
                                               server_default=MemoStatus.TODO.value, nullable=False)
    memo: Mapped[Optional[str]] = mapped_column(Text)                                     # 최대 1,000자 (화면·API 검증)
    updated_by: Mapped[Optional[int]] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(),
                                                 nullable=False)

    review: Mapped[Review] = relationship(backref=backref("memo", uselist=False, cascade="all, delete-orphan",
                                                          passive_deletes=True))
