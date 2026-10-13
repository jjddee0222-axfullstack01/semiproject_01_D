"""
PIN POINT REVIEW - Pydantic v2 스키마 (API 요청 / 응답)

근거 (GitHub: jjddee0222-axfullstack01/semiproject_01_D)
  - docs/05_api_spec.md      : 엔드포인트, 요청 필드, 페이지네이션, 필터, 오류 코드
  - docs/04_database_design.md (ERD) / backend/models.py : 필드 이름·타입·ENUM 값
  - docs/06_architecture.md  : 7장-2 표기법 통일(snake_case, 정수 ID), 7장-3 공통 오류 형식 {code, message}

규칙
  - 필드 이름은 DB 컬럼과 같은 snake_case, ID 는 모두 int
  - ENUM 은 models.py 의 Enum 을 그대로 사용 (값이 한 곳에서만 정의되도록)
  - *Out 스키마는 ORM 객체에서 바로 만들 수 있음:  UserOut.model_validate(user)
  - 비밀번호 해시, 세션 토큰 해시, 임베딩(JSON 벡터)은 응답에 절대 포함하지 않음

목차
  0. 공통 (기반 클래스, 페이지네이션, 기간·상품 필터, 오류)
  1. 인증·계정        /auth/*, /users/me
  2. 상품            /products
  3. 리뷰·블라인드    /products/{id}/reviews, /reviews/{id}, /reviews/{id}/blind
  4. CS 답글         /reviews/{id}/replies, /replies/{id}
  5. 통계·대시보드    /stats/*
  6. 위험 키워드      /risk-keywords
  7. 내보내기·LLM    /exports/*, /reviews/{id}/reply-suggestions
  8. 데이터 파이프라인 /internal/*
  9. 현재 화면 전용   리뷰 등록 API, 의견 보내기
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Generic, Literal, Optional, TypeVar

from pydantic import (AliasChoices, BaseModel, ConfigDict, Field,
                      field_validator, model_validator)

try:
    from .models import BlindAction, IssueType, MallPlatform, Polarity, ReviewStatus, UserStatus
except ImportError:
    from models import BlindAction, IssueType, MallPlatform, Polarity, ReviewStatus, UserStatus


# ══════════════════════════════════════════════
# 0. 공통
# ══════════════════════════════════════════════
class RequestModel(BaseModel):
    """요청 본문: 정의되지 않은 필드는 거부(422), 문자열 앞뒤 공백 제거"""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    """응답: ORM 객체에서 바로 변환 (from_attributes)"""
    model_config = ConfigDict(from_attributes=True)


# ── 공통 입력 규칙 (화면·API가 같은 규칙을 쓰도록 함수로도 제공)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,64}$")
PASSWORD_MESSAGE = "비밀번호는 8~64자이며 영어 대/소문자, 숫자, 특수문자를 모두 포함해야 합니다."


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_PATTERN.match(value) or len(value) > 255:
        raise ValueError("이메일 형식이 올바르지 않습니다.")
    return value


def validate_password(value: str) -> str:
    if not PASSWORD_PATTERN.match(value):
        raise ValueError(PASSWORD_MESSAGE)
    return value


def normalize_business_number(value: str) -> str:
    """'123-45-67890' → '1234567890' (ERD: CHAR(10))"""
    digits = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d{10}", digits):
        raise ValueError("사업자 등록 번호는 숫자 10자리여야 합니다. (예: 123-45-67890)")
    return digits


# ── 페이지네이션: ?page=1&size=20 → {items, page, size, total}
T = TypeVar("T")


class PageParams(RequestModel):
    page: int = Field(1, ge=1, description="1부터 시작")
    size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class Page(ResponseModel, Generic[T]):
    items: list[T]
    page: int
    size: int
    total: int


# ── 기간 필터: ?from=YYYY-MM-DD&to=YYYY-MM-DD  (기간을 받는 모든 쿼리가 상속 → 검사 규칙 한 곳)
class DateRange(RequestModel):
    model_config = ConfigDict(populate_by_name=True)   # 파이썬 코드에서는 date_from 으로도 생성 가능

    date_from: Optional[date] = Field(None, alias="from")   # 'from' 은 파이썬 예약어라 alias 사용
    date_to: Optional[date] = Field(None, alias="to")

    @model_validator(mode="after")
    def _check_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("시작일(from)은 종료일(to)보다 늦을 수 없습니다.")
        return self


# ── 기간·상품 필터: ?product_id=&from=&to=
class PeriodFilter(DateRange):
    product_id: Optional[int] = Field(None, ge=1)


# ── 공통 오류 형식 (06_architecture 7장-3)
class ErrorResponse(ResponseModel):
    code: str = Field(..., examples=["REVIEW_ALREADY_BLINDED"])
    message: str = Field(..., examples=["이미 블라인드된 리뷰입니다."])
    errors: Optional[list[dict]] = Field(None, description="422 일 때만: 항목별 오류 [{loc, message}]")


# 엔드포인트에 붙여 쓰는 공통 오류 응답 문서  예) @app.post(..., responses=ERROR_RESPONSES)
ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "미인증"},
    403: {"model": ErrorResponse, "description": "권한 없음 (본인 상품 아님)"},
    404: {"model": ErrorResponse, "description": "대상 없음"},
    409: {"model": ErrorResponse, "description": "상태 충돌 (중복, 이미 블라인드 등)"},
}


# ══════════════════════════════════════════════
# 1. 인증·계정 (E1)
# ══════════════════════════════════════════════
class SignupRequest(RequestModel):
    """POST /auth/signup  → 201 / 409(이메일·사업자번호 중복) / 422"""
    email: str = Field(..., max_length=255, examples=["seller@pinpoint.kr"])
    password: str = Field(..., examples=["Pinpoint1!"])
    name: str = Field(..., min_length=1, max_length=50)
    mall_name: str = Field(..., min_length=1, max_length=100)
    mall_platform: MallPlatform
    business_number: str = Field(..., examples=["123-45-67890"])

    _email = field_validator("email")(normalize_email)
    _password = field_validator("password")(validate_password)
    _business_number = field_validator("business_number")(normalize_business_number)


class LoginRequest(RequestModel):
    """POST /auth/login  → 200 + Set-Cookie: session_id / 401"""
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()       # 로그인은 형식 검사 없이 소문자로만 맞춤 (실패 이유 노출 방지)


class UserOut(ResponseModel):
    """GET /users/me  (password_hash 제외)"""
    id: int
    email: str
    name: str
    mall_name: str
    mall_platform: MallPlatform
    business_number: str
    status: UserStatus
    created_at: datetime


class UserUpdate(RequestModel):
    """PATCH /users/me  — 보낸 필드만 수정 (쇼핑몰명·플랫폼 등)"""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    mall_name: Optional[str] = Field(None, min_length=1, max_length=100)
    mall_platform: Optional[MallPlatform] = None
    business_number: Optional[str] = None

    @field_validator("business_number")
    @classmethod
    def _business_number(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_business_number(value)

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.model_fields_set:
            raise ValueError("수정할 항목을 하나 이상 보내야 합니다.")
        return self


class PasswordChangeRequest(RequestModel):
    """비밀번호 변경 (설정 화면) — API 명세에는 별도 경로가 없어 PATCH /users/me/password 로 제안"""
    current_password: str = Field(..., min_length=1)
    new_password: str

    _new_password = field_validator("new_password")(validate_password)

    @model_validator(mode="after")
    def _different(self):
        if self.current_password == self.new_password:
            raise ValueError("새 비밀번호가 현재 비밀번호와 같습니다.")
        return self


class WithdrawRequest(RequestModel):
    """DELETE /users/me  (body: password 재확인) → 204 / 401"""
    password: str = Field(..., min_length=1)


# ══════════════════════════════════════════════
# 2. 상품 (E2)
# ══════════════════════════════════════════════
class ProductListQuery(PageParams):
    """GET /products?q=&category=&page=&size="""
    q: Optional[str] = Field(None, max_length=100, description="상품명 검색어")
    category: Optional[str] = Field(None, max_length=100)


class ProductOut(ResponseModel):
    """상품 기본 정보 (description_embedding 제외)"""
    id: int
    seller_id: int
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime


class ProductListItem(ProductOut):
    """GET /products 목록 한 줄 (블라인드 리뷰 제외 집계)"""
    review_count: int = 0
    avg_rating: float = Field(0.0, ge=0, le=5)


class ProductDetailOut(ProductListItem):
    """GET /products/{product_id}  — 리뷰 수, 평균 평점 요약 포함"""
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    risky_count: int = Field(0, description="severity ≥ 2 인 리뷰 수")


# ══════════════════════════════════════════════
# 3. 리뷰 조회·블라인드 (E2)
# ══════════════════════════════════════════════
class ReviewListQuery(PageParams, DateRange):
    """GET /products/{product_id}/reviews?status=VISIBLE|BLINDED&sentiment=&rating=&from=&to="""
    status: ReviewStatus = Field(ReviewStatus.VISIBLE, description="기본은 VISIBLE (블라인드 리뷰 제외)")
    sentiment: Optional[Polarity] = None
    rating: Optional[int] = Field(None, ge=1, le=5)


class ReviewAnalysisOut(ResponseModel):
    sentiment: Polarity
    sentiment_score: Optional[float] = None
    severity: int = Field(..., ge=0, le=3)
    issue_type: Optional[IssueType] = None
    model_version: str
    analyzed_at: datetime


class ReviewAnalysisBrief(ResponseModel):
    """목록용 요약 (감성·심각도)"""
    sentiment: Polarity
    severity: int = Field(..., ge=0, le=3)
    issue_type: Optional[IssueType] = None


class ReviewOut(ResponseModel):
    """리뷰 목록 한 줄 — 평점, 작성일, 본문, 감성, 상태"""
    id: int
    product_id: int
    reviewer_name: Optional[str] = None
    rating: int = Field(..., ge=1, le=5)
    content_raw: str
    reviewed_at: date
    status: ReviewStatus
    analysis: Optional[ReviewAnalysisBrief] = None


class ReviewKeywordOut(ResponseModel):
    """리뷰에 매핑된 키워드 (ORM: ReviewKeyword → keyword.word 를 평탄화)"""
    keyword_id: int
    word: str
    polarity: Polarity
    score: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data):
        if hasattr(data, "keyword"):            # ORM ReviewKeyword 객체
            return {"keyword_id": data.keyword_id, "word": data.keyword.word,
                    "polarity": data.keyword.polarity, "score": data.score}
        return data


class ReviewDetailOut(ReviewOut):
    """GET /reviews/{review_id}  — 분석 결과, 키워드, 답글 포함"""
    content_clean: Optional[str] = None
    blind_reason: Optional[str] = None
    blinded_by: Optional[int] = None
    blinded_at: Optional[datetime] = None
    created_at: datetime
    analysis: Optional[ReviewAnalysisOut] = None
    keywords: list[ReviewKeywordOut] = Field(default_factory=list,
                                             validation_alias=AliasChoices("keyword_links", "keywords"))
    replies: list[ReplyOut] = Field(default_factory=list,
                                    validation_alias=AliasChoices("root_replies", "replies"),
                                    description="최상위 답글 (하위 답글은 children)")


class BlindRequest(RequestModel):
    """POST /reviews/{review_id}/blind  (reason 필수 → 누락 시 422)"""
    reason: str = Field(..., min_length=1, max_length=500, examples=["근거 없는 악성 비방"])


class BlindLogOut(ResponseModel):
    """GET /reviews/{review_id}/blind-logs"""
    id: int
    review_id: int
    actor_id: Optional[int] = None          # 처리자 탈퇴 시 NULL (익명화)
    action: BlindAction
    reason: Optional[str] = None
    created_at: datetime


# ══════════════════════════════════════════════
# 4. 리뷰 답글 CS (E3)
# ══════════════════════════════════════════════
class ReplyCreate(RequestModel):
    """POST /reviews/{review_id}/replies → 201 / 403 / 409(블라인드된 리뷰)"""
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[int] = Field(None, ge=1, description="하위 답글이면 상위 답글 ID")


class ReplyUpdate(RequestModel):
    """PATCH /replies/{reply_id}  (작성자 본인만)"""
    content: str = Field(..., min_length=1, max_length=2000)


class ReplyOut(ResponseModel):
    """GET /reviews/{review_id}/replies  — 답글 트리"""
    id: int
    review_id: int
    parent_id: Optional[int] = None
    author_id: Optional[int] = None         # 작성자 탈퇴 시 NULL (익명화)
    content: str
    created_at: datetime
    updated_at: datetime
    children: list[ReplyOut] = Field(default_factory=list)


# ══════════════════════════════════════════════
# 5. 통계·대시보드 (E5)   — 모두 status='VISIBLE' 리뷰만 집계
# ══════════════════════════════════════════════
class StatsQuery(PeriodFilter):
    """GET /stats/*  공통 필터 (?product_id=&from=&to=)"""


class MonthlyTrendItem(ResponseModel):
    """GET /stats/monthly-trend  → [{month, count, avg_rating}]"""
    month: str = Field(..., pattern=r"^\d{4}-\d{2}$", examples=["2026-10"])
    count: int
    avg_rating: float = Field(..., ge=0, le=5)


class SentimentRatioItem(ResponseModel):
    sentiment: Polarity
    count: int
    ratio: float = Field(..., ge=0, le=1, description="0~1 (프론트에서 ×100 하여 % 표시)")


class SentimentRatioOut(ResponseModel):
    """GET /stats/sentiment-ratio — 긍/부정/중립 비율과 건수"""
    total: int
    items: list[SentimentRatioItem]


class KeywordTopQuery(StatsQuery):
    """GET /stats/keywords/top?limit=10&polarity="""
    limit: int = Field(10, ge=1, le=50)
    polarity: Optional[Polarity] = None


class KeywordRankItem(ResponseModel):
    rank: int = Field(..., ge=1)
    keyword_id: int
    word: str
    polarity: Polarity
    count: int = Field(..., description="해당 키워드가 등장한 리뷰 수")


class RiskReviewQuery(StatsQuery, PageParams):
    """GET /stats/risk-reviews?issue_type=PRODUCT|DELIVERY|PACKAGING&sort=severity|latest (페이지네이션)"""
    issue_type: Optional[IssueType] = None
    sort: Literal["severity", "latest"] = Field("severity", description="severity: 심각도순(같으면 최신순), latest: 최신순")


class RiskReviewItem(ResponseModel):
    """위험 리뷰 — 최신순·심각도순 정렬 결과 한 줄"""
    review_id: int
    product_id: int
    product_name: str
    reviewer_name: Optional[str] = None
    rating: int
    content_raw: str
    reviewed_at: date
    sentiment: Polarity
    severity: int = Field(..., ge=0, le=3)
    issue_type: Optional[IssueType] = None


class IssueTypeCountItem(ResponseModel):
    issue_type: IssueType
    count: int
    ratio: float = Field(..., ge=0, le=1)


class IssueTypeDistributionOut(ResponseModel):
    """GET /stats/issue-types — 상품 문제 vs 유통·포장 문제 분포"""
    total: int
    items: list[IssueTypeCountItem]


class StatsSummaryOut(ResponseModel):
    """GET /stats/summary — 대시보드 상단 카드"""
    total_reviews: int
    avg_rating: float = Field(..., ge=0, le=5)
    negative_ratio: float = Field(..., ge=0, le=1)
    risky_count: int


class CompareQuery(DateRange):
    """GET /stats/compare?product_ids=1,2&from=&to=  (상품 2개)"""
    product_ids: list[int]

    @field_validator("product_ids", mode="before")
    @classmethod
    def _split(cls, value):
        # ?product_ids=1,2 (명세) 와 ?product_ids=1&product_ids=2 둘 다 허용
        if isinstance(value, str):
            value = [value]
        if isinstance(value, (list, tuple)):
            value = [p.strip() for v in value for p in str(v).split(",") if p.strip()]
        return value

    @field_validator("product_ids")
    @classmethod
    def _two_distinct(cls, value: list[int]) -> list[int]:
        if len(value) != 2 or len(set(value)) != 2 or min(value) < 1:
            raise ValueError("서로 다른 상품 ID 2개를 입력해야 합니다. (예: product_ids=1,2)")
        return value


class CompareProductItem(ResponseModel):
    product_id: int
    name: str
    review_count: int
    avg_rating: float = Field(..., ge=0, le=5)
    sentiment: list[SentimentRatioItem]
    top_keywords: list[KeywordRankItem]


class CompareOut(ResponseModel):
    """GET /stats/compare — 평점, 키워드, 긍/부정 비율 비교"""
    products: list[CompareProductItem] = Field(..., min_length=2, max_length=2)


# ══════════════════════════════════════════════
# 6. 위험 키워드 설정
# ══════════════════════════════════════════════
class RiskKeywordCreate(RequestModel):
    """POST /risk-keywords (word, weight) → 409(중복)"""
    word: str = Field(..., min_length=1, max_length=100)
    weight: int = Field(1, ge=1, le=10, description="클수록 위험 (ERD: TINYINT)")


class RiskKeywordUpdate(RequestModel):
    """PATCH /risk-keywords/{id} — 보낸 필드만 수정"""
    word: Optional[str] = Field(None, min_length=1, max_length=100)
    weight: Optional[int] = Field(None, ge=1, le=10)

    @model_validator(mode="after")
    def _not_empty(self):
        if not self.model_fields_set:
            raise ValueError("수정할 항목(word 또는 weight)을 보내야 합니다.")
        return self


class RiskKeywordOut(ResponseModel):
    id: int
    seller_id: int
    word: str
    weight: int
    created_at: datetime


# ══════════════════════════════════════════════
# 7. 내보내기·LLM
# ══════════════════════════════════════════════
class ExportQuery(StatsQuery):
    """GET /exports/stats.csv, /exports/reviews.csv — 통계 API 와 같은 필터 (응답은 text/csv)"""


class ReplySuggestionOut(ResponseModel):
    """POST·GET /reviews/{review_id}/reply-suggestions — LLM 사과 답글 초안"""
    id: int
    review_id: int
    draft: str
    llm_model: str
    created_at: datetime


# ══════════════════════════════════════════════
# 8. 데이터 파이프라인 (내부용, 외부 노출 금지)
# ══════════════════════════════════════════════
class IngestRequest(RequestModel):
    """POST /internal/ingest — 데이터셋 적재 실행"""
    batch_name: str = Field(..., min_length=1, max_length=255, examples=["naver_reviews_2026_10"])
    source_path: str = Field(..., min_length=1, description="서버에서 읽을 데이터셋 파일 경로 (CSV 등)")
    seller_id: int = Field(..., ge=1, description="적재한 상품·리뷰를 소유할 셀러")


class IngestLogOut(ResponseModel):
    """GET /internal/ingest-logs — 적재 이력 (중복·결측 건수)"""
    id: int
    batch_name: str
    total_count: int
    duplicate_count: int
    missing_count: int
    run_at: datetime


class AnalyzeRequest(RequestModel):
    """POST /internal/analyze — 미분석 리뷰 분석 실행"""
    limit: int = Field(1000, ge=1, le=100_000, description="한 번에 분석할 최대 리뷰 수")
    reanalyze_model_version: Optional[str] = Field(
        None, description="이 model_version 으로 분석된 리뷰를 다시 분석 (모델 교체 시)")


class AnalyzeResult(ResponseModel):
    analyzed_count: int
    model_version: str


# ══════════════════════════════════════════════
# 9. 현재 화면 전용 (API 명세 외)
# ══════════════════════════════════════════════
class ReviewCreate(RequestModel):
    """POST /api/reviews — 리뷰 등록 (테스트·연동용). 등록 즉시 자동 분석"""
    product_id: int = Field(..., ge=1)
    content: str = Field(..., min_length=1, max_length=5000)
    rating: int = Field(..., ge=1, le=5)
    reviewer_name: Optional[str] = Field(None, max_length=50)
    reviewed_at: Optional[date] = None

    @field_validator("reviewed_at")
    @classmethod
    def _not_future(cls, value: Optional[date]) -> Optional[date]:
        if value and value > date.today():
            raise ValueError("작성일은 미래 날짜일 수 없습니다.")
        return value


class ReviewCreateResult(ResponseModel):
    id: int
    sentiment: Polarity
    severity: int = Field(..., ge=0, le=3)
    issue_type: Optional[IssueType] = None
    is_risky: bool


class FeedbackCreate(RequestModel):
    """의견 보내기 (보조 테이블 feedbacks)"""
    complaint: str = Field(..., min_length=1, max_length=5000)
    suggestion: str = Field(..., min_length=1, max_length=5000)


# 자기 자신·뒤쪽 클래스를 참조하는 스키마 완성
ReplyOut.model_rebuild()
ReviewDetailOut.model_rebuild()
