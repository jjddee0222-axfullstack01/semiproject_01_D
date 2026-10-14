"""
PIN POINT REVIEW - REST API v1  (docs/05_api_spec.md)

Base URL : /api/v1          문서: http://127.0.0.1:8000/docs
인증     : 세션 쿠키 session_id (/auth/signup, /auth/login 제외 전부 필요)
오류     : {"code": "...", "message": "..."}  (422 는 errors 목록 추가)
소유권   : 상품·리뷰·답글·위험 키워드는 본인 상품 기준. 없으면 404, 남의 것이면 403
블라인드 : 통계·위험 리뷰·키워드·CSV 는 status='VISIBLE' 리뷰만 집계 (_scope 한 곳에서 관리)
"""
import csv
import hmac
import io
import os
from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import Select, case, distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

try:
    from .analysis import MODEL_VERSION, RISK_SEVERITY
    from .auth import clear_cookie, delete_account, end_session, login_required, start_session
    from .database import add_default_risk_keywords, analyze_and_save, seller_risk_keywords
    from .db import get_session
    from .models import (BlindAction, IngestLog, IssueType, Keyword, Polarity, Product,
                         ReplySuggestion, Review, ReviewAnalysis, ReviewBlindLog, ReviewKeyword,
                         ReviewReply, ReviewStatus, RiskKeyword, User, UserStatus)
    from .pipeline import IngestError, analyze_pending, ingest_csv
    from .reply_drafts import generate_reply_draft
    from . import schemas as S
    from .security import hash_password, verify_password
except ImportError:
    from analysis import MODEL_VERSION, RISK_SEVERITY
    from auth import clear_cookie, delete_account, end_session, login_required, start_session
    from database import add_default_risk_keywords, analyze_and_save, seller_risk_keywords
    from db import get_session
    from models import (BlindAction, IngestLog, IssueType, Keyword, Polarity, Product,
                        ReplySuggestion, Review, ReviewAnalysis, ReviewBlindLog, ReviewKeyword,
                        ReviewReply, ReviewStatus, RiskKeyword, User, UserStatus)
    from pipeline import IngestError, analyze_pending, ingest_csv
    from reply_drafts import generate_reply_draft
    import schemas as S
    from security import hash_password, verify_password

router = APIRouter(prefix="/api/v1", responses=S.ERROR_RESPONSES)
# ※ FastAPI 는 함수 이름을 라우트 이름으로 쓰고 url_for() 는 이름으로 찾으므로,
#   화면 라우트(main.py)와 같은 함수 이름(login, signup, logout, withdraw …)을 쓰지 않도록 api_ 를 붙임

DB = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(login_required)]


# ══════════════════════════════════════════════
# 오류 처리
# ══════════════════════════════════════════════
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _not_found(what: str, label: str) -> ApiError:
    return ApiError(404, f"{what}_NOT_FOUND", f"{label}을(를) 찾을 수 없습니다.")


FORBIDDEN = ApiError(403, "FORBIDDEN", "본인 상품의 데이터에만 접근할 수 있습니다.")


def setup_api(app: FastAPI) -> None:
    """main.py 에서 호출: 라우터 등록 + /api/v1 오류 형식 통일"""
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith("/api/v1"):
            return await request_validation_exception_handler(request, exc)
        errors = [{"loc": [str(p) for p in e.get("loc", ())],
                   "message": str(e.get("msg", "")).removeprefix("Value error, ")} for e in exc.errors()]
        message = errors[0]["message"] if errors else "입력값이 올바르지 않습니다."
        return JSONResponse({"code": "VALIDATION_ERROR", "message": message, "errors": errors},
                            status_code=422)


# ══════════════════════════════════════════════
# 공통 조회 도우미
# ══════════════════════════════════════════════
def owned_product(db: Session, product_id: int, user: User) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise _not_found("PRODUCT", "상품")
    if product.seller_id != user.id:
        raise FORBIDDEN
    return product


def owned_review(db: Session, review_id: int, user: User) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise _not_found("REVIEW", "리뷰")
    if review.product.seller_id != user.id:
        raise FORBIDDEN
    return review


def owned_reply(db: Session, reply_id: int, user: User) -> ReviewReply:
    reply = db.get(ReviewReply, reply_id)
    if reply is None:
        raise _not_found("REPLY", "답글")
    if reply.review.product.seller_id != user.id:
        raise FORBIDDEN
    if reply.author_id != user.id:
        raise ApiError(403, "NOT_REPLY_AUTHOR", "답글 작성자 본인만 수정·삭제할 수 있습니다.")
    return reply


def _scope(db: Session, user: User, f: S.PeriodFilter) -> Select:
    """통계·위험 리뷰·키워드·CSV 의 공통 시작점: 내 상품의 VISIBLE 리뷰 + 상품·기간 필터"""
    if f.product_id is not None:
        owned_product(db, f.product_id, user)
    stmt = (select(Review).join(Review.product)
            .where(Product.seller_id == user.id, Review.status == ReviewStatus.VISIBLE))
    if f.product_id is not None:
        stmt = stmt.where(Review.product_id == f.product_id)
    if f.date_from:
        stmt = stmt.where(Review.reviewed_at >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Review.reviewed_at <= f.date_to)
    return stmt


def _count(db: Session, stmt: Select) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _month(db: Session, column):
    """날짜 → 'YYYY-MM' (MariaDB: DATE_FORMAT, SQLite(테스트): strftime)"""
    if db.get_bind().dialect.name == "sqlite":
        return func.strftime("%Y-%m", column)
    return func.date_format(column, "%Y-%m")


def _ratio(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def _no_content() -> Response:
    return Response(status_code=204)


# ══════════════════════════════════════════════
# 1. 인증·계정 (E1)
# ══════════════════════════════════════════════
@router.post("/auth/signup", status_code=201, response_model=S.UserOut, tags=["인증·계정"])
def api_signup(body: S.SignupRequest, db: DB):
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise ApiError(409, "EMAIL_DUPLICATED", "이미 가입된 이메일입니다.")
    if db.scalar(select(User.id).where(User.business_number == body.business_number)):
        raise ApiError(409, "BUSINESS_NUMBER_DUPLICATED", "이미 등록된 사업자 등록 번호입니다.")
    user = User(email=body.email, password_hash=hash_password(body.password), name=body.name,
                mall_name=body.mall_name, mall_platform=body.mall_platform,
                business_number=body.business_number)
    db.add(user)
    add_default_risk_keywords(db, user)
    db.commit()
    return S.UserOut.model_validate(user)


@router.post("/auth/login", response_model=S.UserOut, tags=["인증·계정"])
def api_login(body: S.LoginRequest, db: DB):
    user = db.scalar(select(User).where(User.email == body.email))
    if (user is None or user.status != UserStatus.ACTIVE
            or not verify_password(body.password, user.password_hash)):
        raise ApiError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
    response = JSONResponse(S.UserOut.model_validate(user).model_dump(mode="json"))
    start_session(db, user, response)              # Set-Cookie: session_id
    return response


@router.post("/auth/logout", status_code=204, tags=["인증·계정"])
def api_logout(request: Request, db: DB):
    response = _no_content()
    end_session(db, request, response)
    return response


@router.get("/users/me", response_model=S.UserOut, tags=["인증·계정"])
def get_me(user: CurrentUser):
    return S.UserOut.model_validate(user)


@router.patch("/users/me", response_model=S.UserOut, tags=["인증·계정"])
def update_me(body: S.UserUpdate, user: CurrentUser, db: DB):
    changes = body.model_dump(exclude_unset=True)
    if "business_number" in changes and db.scalar(
            select(User.id).where(User.business_number == changes["business_number"], User.id != user.id)):
        raise ApiError(409, "BUSINESS_NUMBER_DUPLICATED", "이미 다른 계정에 등록된 사업자 등록 번호입니다.")
    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)
    db.commit()
    return S.UserOut.model_validate(user)


@router.patch("/users/me/password", status_code=204, tags=["인증·계정"])
def change_password(body: S.PasswordChangeRequest, user: CurrentUser, db: DB):
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(401, "INVALID_PASSWORD", "현재 비밀번호가 올바르지 않습니다.")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return _no_content()


@router.delete("/users/me", status_code=204, tags=["인증·계정"])
def api_withdraw(body: S.WithdrawRequest, user: CurrentUser, db: DB):
    """US-04: 비밀번호 재확인 → 계정과 계정의 모든 데이터 삭제(하드 삭제, D5) → 쿠키 만료"""
    if not verify_password(body.password, user.password_hash):
        raise ApiError(401, "INVALID_PASSWORD", "비밀번호가 올바르지 않습니다.")
    delete_account(db, user)
    db.commit()
    response = _no_content()
    clear_cookie(response)
    return response


# ══════════════════════════════════════════════
# 2. 상품 (E2)
# ══════════════════════════════════════════════
def _review_agg():
    """상품별 VISIBLE 리뷰 수·평균 평점 서브쿼리"""
    return (select(Review.product_id,
                   func.count(Review.id).label("review_count"),
                   func.avg(Review.rating).label("avg_rating"))
            .where(Review.status == ReviewStatus.VISIBLE)
            .group_by(Review.product_id).subquery())


@router.get("/products", response_model=S.Page[S.ProductListItem], tags=["상품"])
def list_products(params: Annotated[S.ProductListQuery, Query()], user: CurrentUser, db: DB):
    base = select(Product).where(Product.seller_id == user.id)
    if params.q:
        base = base.where(Product.name.contains(params.q, autoescape=True))
    if params.category:
        base = base.where(Product.category == params.category)
    total = _count(db, base)

    agg = _review_agg()
    rows = db.execute(
        base.add_columns(func.coalesce(agg.c.review_count, 0), func.coalesce(agg.c.avg_rating, 0))
        .outerjoin(agg, agg.c.product_id == Product.id)
        .order_by(Product.id).limit(params.size).offset(params.offset)
    ).all()
    items = [S.ProductListItem.model_validate(p).model_copy(
        update={"review_count": int(n), "avg_rating": round(float(avg), 2)}) for p, n, avg in rows]
    return S.Page[S.ProductListItem](items=items, page=params.page, size=params.size, total=total)


@router.get("/products/{product_id}", response_model=S.ProductDetailOut, tags=["상품"])
def get_product(product_id: int, user: CurrentUser, db: DB):
    product = owned_product(db, product_id, user)
    row = db.execute(
        select(func.count(Review.id), func.coalesce(func.avg(Review.rating), 0),
               func.coalesce(func.sum(case((ReviewAnalysis.sentiment == Polarity.POS, 1), else_=0)), 0),
               func.coalesce(func.sum(case((ReviewAnalysis.sentiment == Polarity.NEG, 1), else_=0)), 0),
               func.coalesce(func.sum(case((ReviewAnalysis.sentiment == Polarity.NEU, 1), else_=0)), 0),
               func.coalesce(func.sum(case((ReviewAnalysis.severity >= RISK_SEVERITY, 1), else_=0)), 0))
        .select_from(Review).outerjoin(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
        .where(Review.product_id == product.id, Review.status == ReviewStatus.VISIBLE)
    ).one()
    n, avg, pos, neg, neu, risky = row
    return S.ProductDetailOut.model_validate(product).model_copy(update={
        "review_count": int(n), "avg_rating": round(float(avg), 2), "positive_count": int(pos),
        "negative_count": int(neg), "neutral_count": int(neu), "risky_count": int(risky)})


# ══════════════════════════════════════════════
# 3. 리뷰 조회·블라인드 (E2)
# ══════════════════════════════════════════════
@router.get("/products/{product_id}/reviews", response_model=S.Page[S.ReviewOut], tags=["리뷰"])
def list_reviews(product_id: int, params: Annotated[S.ReviewListQuery, Query()], user: CurrentUser, db: DB):
    owned_product(db, product_id, user)
    stmt = select(Review).where(Review.product_id == product_id, Review.status == params.status)
    if params.sentiment:
        stmt = stmt.join(Review.analysis).where(ReviewAnalysis.sentiment == params.sentiment)
    if params.rating:
        stmt = stmt.where(Review.rating == params.rating)
    if params.date_from:
        stmt = stmt.where(Review.reviewed_at >= params.date_from)
    if params.date_to:
        stmt = stmt.where(Review.reviewed_at <= params.date_to)
    total = _count(db, stmt)
    reviews = db.scalars(stmt.options(selectinload(Review.analysis))
                         .order_by(Review.reviewed_at.desc(), Review.id.desc())
                         .limit(params.size).offset(params.offset)).all()
    return S.Page[S.ReviewOut](items=[S.ReviewOut.model_validate(r) for r in reviews],
                               page=params.page, size=params.size, total=total)


def _detail(review: Review) -> S.ReviewDetailOut:
    return S.ReviewDetailOut.model_validate(review)


@router.get("/reviews/{review_id}", response_model=S.ReviewDetailOut, tags=["리뷰"])
def get_review(review_id: int, user: CurrentUser, db: DB):
    return _detail(owned_review(db, review_id, user))


@router.post("/reviews/{review_id}/blind", response_model=S.ReviewDetailOut, tags=["리뷰"])
def blind_review(review_id: int, body: S.BlindRequest, user: CurrentUser, db: DB):
    """악성 리뷰 블라인드 (사유 필수). 이후 통계·위험 리뷰·키워드 집계에서 제외"""
    review = owned_review(db, review_id, user)
    if review.status == ReviewStatus.BLINDED:
        raise ApiError(409, "REVIEW_ALREADY_BLINDED", "이미 블라인드된 리뷰입니다.")
    review.status, review.blind_reason = ReviewStatus.BLINDED, body.reason
    review.blinded_by, review.blinded_at = user.id, datetime.now()
    db.add(ReviewBlindLog(review=review, actor_id=user.id, action=BlindAction.BLIND, reason=body.reason))
    db.commit()
    return _detail(review)


@router.delete("/reviews/{review_id}/blind", response_model=S.ReviewDetailOut, tags=["리뷰"])
def restore_review(review_id: int, user: CurrentUser, db: DB):
    """블라인드 해제(복구)"""
    review = owned_review(db, review_id, user)
    if review.status != ReviewStatus.BLINDED:
        raise ApiError(409, "REVIEW_NOT_BLINDED", "블라인드 상태인 리뷰가 아닙니다.")
    review.status = ReviewStatus.VISIBLE
    review.blind_reason = review.blinded_by = review.blinded_at = None
    db.add(ReviewBlindLog(review=review, actor_id=user.id, action=BlindAction.RESTORE))
    db.commit()
    return _detail(review)


@router.get("/reviews/{review_id}/blind-logs", response_model=list[S.BlindLogOut], tags=["리뷰"])
def blind_logs(review_id: int, user: CurrentUser, db: DB):
    review = owned_review(db, review_id, user)
    return [S.BlindLogOut.model_validate(log) for log in review.blind_logs]


# ══════════════════════════════════════════════
# 4. 리뷰 답글 CS (E3)
# ══════════════════════════════════════════════
@router.get("/reviews/{review_id}/replies", response_model=list[S.ReplyOut], tags=["CS 답글"])
def list_replies(review_id: int, user: CurrentUser, db: DB):
    review = owned_review(db, review_id, user)
    return [S.ReplyOut.model_validate(r) for r in review.root_replies]


@router.post("/reviews/{review_id}/replies", status_code=201, response_model=S.ReplyOut, tags=["CS 답글"])
def create_reply(review_id: int, body: S.ReplyCreate, user: CurrentUser, db: DB):
    review = owned_review(db, review_id, user)
    if review.status == ReviewStatus.BLINDED:
        raise ApiError(409, "REVIEW_BLINDED", "블라인드된 리뷰에는 답글을 등록할 수 없습니다.")
    if body.parent_id is not None:
        parent = db.get(ReviewReply, body.parent_id)
        if parent is None or parent.review_id != review.id:
            raise _not_found("PARENT_REPLY", "상위 답글")
    reply = ReviewReply(review_id=review.id, parent_id=body.parent_id, author_id=user.id, content=body.content)
    db.add(reply)
    db.commit()
    return S.ReplyOut.model_validate(reply)


@router.patch("/replies/{reply_id}", response_model=S.ReplyOut, tags=["CS 답글"])
def update_reply(reply_id: int, body: S.ReplyUpdate, user: CurrentUser, db: DB):
    reply = owned_reply(db, reply_id, user)
    reply.content = body.content
    db.commit()
    db.refresh(reply)
    return S.ReplyOut.model_validate(reply)


@router.delete("/replies/{reply_id}", status_code=204, tags=["CS 답글"])
def delete_reply(reply_id: int, user: CurrentUser, db: DB):
    """하위 답글도 함께 삭제 (D4)"""
    db.delete(owned_reply(db, reply_id, user))
    db.commit()
    return _no_content()


# ══════════════════════════════════════════════
# 5. 통계·대시보드 (E5)
# ══════════════════════════════════════════════
def _sentiment_items(db: Session, scope: Select) -> tuple[int, list[S.SentimentRatioItem]]:
    rows = dict(db.execute(
        scope.join(Review.analysis).with_only_columns(ReviewAnalysis.sentiment, func.count(Review.id))
        .group_by(ReviewAnalysis.sentiment)).all())
    total = sum(rows.values())
    return total, [S.SentimentRatioItem(sentiment=p, count=rows.get(p, 0), ratio=_ratio(rows.get(p, 0), total))
                   for p in Polarity]


def _top_keywords(db: Session, scope: Select, limit: int,
                  polarity: Optional[Polarity] = None) -> list[S.KeywordRankItem]:
    stmt = (scope.join(ReviewKeyword, ReviewKeyword.review_id == Review.id)
            .join(Keyword, Keyword.id == ReviewKeyword.keyword_id)
            .with_only_columns(Keyword.id, Keyword.word, Keyword.polarity, func.count(distinct(Review.id)).label("cnt"))
            .group_by(Keyword.id, Keyword.word, Keyword.polarity)
            .order_by(func.count(distinct(Review.id)).desc(), Keyword.word).limit(limit))
    if polarity:
        stmt = stmt.where(Keyword.polarity == polarity)
    return [S.KeywordRankItem(rank=i, keyword_id=kid, word=w, polarity=pol, count=c)
            for i, (kid, w, pol, c) in enumerate(db.execute(stmt).all(), start=1)]


@router.get("/stats/monthly-trend", response_model=list[S.MonthlyTrendItem], tags=["통계"])
def monthly_trend(params: Annotated[S.StatsQuery, Query()], user: CurrentUser, db: DB):
    month = _month(db, Review.reviewed_at).label("month")
    rows = db.execute(_scope(db, user, params)
                      .with_only_columns(month, func.count(Review.id), func.avg(Review.rating))
                      .group_by(month).order_by(month)).all()
    return [S.MonthlyTrendItem(month=m, count=n, avg_rating=round(float(avg), 2)) for m, n, avg in rows]


@router.get("/stats/sentiment-ratio", response_model=S.SentimentRatioOut, tags=["통계"])
def sentiment_ratio(params: Annotated[S.StatsQuery, Query()], user: CurrentUser, db: DB):
    total, items = _sentiment_items(db, _scope(db, user, params))
    return S.SentimentRatioOut(total=total, items=items)


@router.get("/stats/keywords/top", response_model=list[S.KeywordRankItem], tags=["통계"])
def keywords_top(params: Annotated[S.KeywordTopQuery, Query()], user: CurrentUser, db: DB):
    return _top_keywords(db, _scope(db, user, params), params.limit, params.polarity)


@router.get("/stats/risk-reviews", response_model=S.Page[S.RiskReviewItem], tags=["통계"])
def risk_reviews(params: Annotated[S.RiskReviewQuery, Query()], user: CurrentUser, db: DB):
    stmt = (_scope(db, user, params).join(Review.analysis)
            .where(ReviewAnalysis.severity >= RISK_SEVERITY))
    if params.issue_type:
        stmt = stmt.where(ReviewAnalysis.issue_type == params.issue_type)
    total = _count(db, stmt)
    order = ((ReviewAnalysis.severity.desc(), Review.reviewed_at.desc()) if params.sort == "severity"
             else (Review.reviewed_at.desc(), ReviewAnalysis.severity.desc()))
    rows = db.execute(stmt.add_columns(Product.name, ReviewAnalysis)
                      .order_by(*order, Review.id.desc()).limit(params.size).offset(params.offset)).all()
    items = [S.RiskReviewItem(review_id=r.id, product_id=r.product_id, product_name=name,
                              reviewer_name=r.reviewer_name, rating=r.rating, content_raw=r.content_raw,
                              reviewed_at=r.reviewed_at, sentiment=a.sentiment, severity=a.severity,
                              issue_type=a.issue_type) for r, name, a in rows]
    return S.Page[S.RiskReviewItem](items=items, page=params.page, size=params.size, total=total)


@router.get("/stats/issue-types", response_model=S.IssueTypeDistributionOut, tags=["통계"])
def issue_types(params: Annotated[S.StatsQuery, Query()], user: CurrentUser, db: DB):
    rows = dict(db.execute(
        _scope(db, user, params).join(Review.analysis).where(ReviewAnalysis.issue_type.is_not(None))
        .with_only_columns(ReviewAnalysis.issue_type, func.count(Review.id))
        .group_by(ReviewAnalysis.issue_type)).all())
    total = sum(rows.values())
    return S.IssueTypeDistributionOut(total=total, items=[
        S.IssueTypeCountItem(issue_type=t, count=rows.get(t, 0), ratio=_ratio(rows.get(t, 0), total))
        for t in IssueType])


@router.get("/stats/summary", response_model=S.StatsSummaryOut, tags=["통계"])
def summary(params: Annotated[S.StatsQuery, Query()], user: CurrentUser, db: DB):
    scope = _scope(db, user, params)
    total, avg = db.execute(scope.with_only_columns(func.count(Review.id), func.coalesce(func.avg(Review.rating), 0))).one()
    analyzed, items = _sentiment_items(db, scope)
    negative = next(i.count for i in items if i.sentiment == Polarity.NEG)
    risky = _count(db, scope.join(Review.analysis).where(ReviewAnalysis.severity >= RISK_SEVERITY))
    return S.StatsSummaryOut(total_reviews=total, avg_rating=round(float(avg), 2),
                             negative_ratio=_ratio(negative, analyzed), risky_count=risky)


@router.get("/stats/compare", response_model=S.CompareOut, tags=["통계"])
def compare(params: Annotated[S.CompareQuery, Query()], user: CurrentUser, db: DB):
    result = []
    for pid in params.product_ids:
        product = owned_product(db, pid, user)
        scope = _scope(db, user, S.PeriodFilter(product_id=pid, date_from=params.date_from, date_to=params.date_to))
        n, avg = db.execute(scope.with_only_columns(func.count(Review.id), func.coalesce(func.avg(Review.rating), 0))).one()
        _, sentiment = _sentiment_items(db, scope)
        result.append(S.CompareProductItem(product_id=pid, name=product.name, review_count=n,
                                           avg_rating=round(float(avg), 2), sentiment=sentiment,
                                           top_keywords=_top_keywords(db, scope, 5)))
    return S.CompareOut(products=result)


# ══════════════════════════════════════════════
# 6. 위험 키워드 설정
#    ※ 변경 내용은 이후 분석부터 반영. 기존 리뷰에 반영하려면 /internal/analyze 로 재분석
# ══════════════════════════════════════════════
def _owned_risk_keyword(db: Session, keyword_id: int, user: User) -> RiskKeyword:
    kw = db.get(RiskKeyword, keyword_id)
    if kw is None:
        raise _not_found("RISK_KEYWORD", "위험 키워드")
    if kw.seller_id != user.id:
        raise FORBIDDEN
    return kw


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "RISK_KEYWORD_DUPLICATED", "이미 등록된 위험 키워드입니다.") from None


@router.get("/risk-keywords", response_model=list[S.RiskKeywordOut], tags=["위험 키워드"])
def list_risk_keywords(user: CurrentUser, db: DB):
    rows = db.scalars(select(RiskKeyword).where(RiskKeyword.seller_id == user.id)
                      .order_by(RiskKeyword.weight.desc(), RiskKeyword.word)).all()
    return [S.RiskKeywordOut.model_validate(k) for k in rows]


@router.post("/risk-keywords", status_code=201, response_model=S.RiskKeywordOut, tags=["위험 키워드"])
def create_risk_keyword(body: S.RiskKeywordCreate, user: CurrentUser, db: DB):
    if db.scalar(select(RiskKeyword.id).where(RiskKeyword.seller_id == user.id, RiskKeyword.word == body.word)):
        raise ApiError(409, "RISK_KEYWORD_DUPLICATED", "이미 등록된 위험 키워드입니다.")
    kw = RiskKeyword(seller_id=user.id, word=body.word, weight=body.weight)
    db.add(kw)
    _commit_or_conflict(db)
    return S.RiskKeywordOut.model_validate(kw)


@router.patch("/risk-keywords/{keyword_id}", response_model=S.RiskKeywordOut, tags=["위험 키워드"])
def update_risk_keyword(keyword_id: int, body: S.RiskKeywordUpdate, user: CurrentUser, db: DB):
    kw = _owned_risk_keyword(db, keyword_id, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(kw, field, value)
    _commit_or_conflict(db)
    return S.RiskKeywordOut.model_validate(kw)


@router.delete("/risk-keywords/{keyword_id}", status_code=204, tags=["위험 키워드"])
def delete_risk_keyword(keyword_id: int, user: CurrentUser, db: DB):
    db.delete(_owned_risk_keyword(db, keyword_id, user))
    db.commit()
    return _no_content()


# ══════════════════════════════════════════════
# 7. 내보내기·LLM
# ══════════════════════════════════════════════
def _csv_response(header: list[str], rows: list[list], filename: str) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    # utf-8-sig(BOM): 엑셀에서 열어도 한글이 깨지지 않음
    return Response(content=buf.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/exports/stats.csv", tags=["내보내기"], response_class=Response)
def export_stats(params: Annotated[S.ExportQuery, Query()], user: CurrentUser, db: DB):
    """월별 리뷰 수·평균 평점·긍/부정/중립·위험 리뷰 수"""
    month = _month(db, Review.reviewed_at).label("month")
    count_if = lambda cond: func.coalesce(func.sum(case((cond, 1), else_=0)), 0)  # noqa: E731
    rows = db.execute(
        _scope(db, user, params).outerjoin(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
        .with_only_columns(month, func.count(Review.id), func.avg(Review.rating),
                           count_if(ReviewAnalysis.sentiment == Polarity.POS),
                           count_if(ReviewAnalysis.sentiment == Polarity.NEG),
                           count_if(ReviewAnalysis.sentiment == Polarity.NEU),
                           count_if(ReviewAnalysis.severity >= RISK_SEVERITY))
        .group_by(month).order_by(month)).all()
    data = [[m, n, round(float(avg), 2), int(p), int(ng), int(nu), int(rk)] for m, n, avg, p, ng, nu, rk in rows]
    return _csv_response(["month", "review_count", "avg_rating", "positive", "negative", "neutral", "risky"],
                         data, f"pinpoint_stats_{date.today():%Y%m%d}.csv")


@router.get("/exports/reviews.csv", tags=["내보내기"], response_class=Response)
def export_reviews(params: Annotated[S.ExportQuery, Query()], user: CurrentUser, db: DB):
    """분석된 리뷰 목록 (블라인드 제외)"""
    rows = db.execute(
        _scope(db, user, params).outerjoin(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
        .add_columns(Product.name, ReviewAnalysis)
        .order_by(Review.reviewed_at.desc(), Review.id.desc())).all()
    data = [[r.id, r.product_id, name, r.reviewer_name or "", r.rating, r.reviewed_at.isoformat(),
             a.sentiment.value if a else "", a.severity if a else "",
             a.issue_type.value if a and a.issue_type else "", r.content_raw, r.content_clean or ""]
            for r, name, a in rows]
    return _csv_response(["review_id", "product_id", "product_name", "reviewer_name", "rating", "reviewed_at",
                          "sentiment", "severity", "issue_type", "content_raw", "content_clean"],
                         data, f"pinpoint_reviews_{date.today():%Y%m%d}.csv")


@router.post("/reviews/{review_id}/reply-suggestions", status_code=201,
             response_model=S.ReplySuggestionOut, tags=["LLM 답글 추천"])
def create_reply_suggestion(review_id: int, user: CurrentUser, db: DB):
    review = owned_review(db, review_id, user)
    if review.status == ReviewStatus.BLINDED:
        raise ApiError(409, "REVIEW_BLINDED", "블라인드된 리뷰입니다.")
    if review.analysis is None:
        analyze_and_save(db, review, seller_risk_keywords(db, user.id))
        db.flush()
    if review.analysis.sentiment == Polarity.POS:
        raise ApiError(409, "NOT_NEGATIVE_REVIEW", "사과 답글 초안은 부정 리뷰에만 만들 수 있습니다.")
    draft, model = generate_reply_draft(review, user.mall_name)
    suggestion = ReplySuggestion(review_id=review.id, draft=draft, llm_model=model)
    db.add(suggestion)
    db.commit()
    return S.ReplySuggestionOut.model_validate(suggestion)


@router.get("/reviews/{review_id}/reply-suggestions", response_model=list[S.ReplySuggestionOut],
            tags=["LLM 답글 추천"])
def list_reply_suggestions(review_id: int, user: CurrentUser, db: DB):
    review = owned_review(db, review_id, user)
    return [S.ReplySuggestionOut.model_validate(s)
            for s in sorted(review.reply_suggestions, key=lambda s: (s.created_at, s.id), reverse=True)]


# ══════════════════════════════════════════════
# 8. 데이터 파이프라인 (내부용) — 세션이 아니라 X-Internal-Key 헤더로만 허용, /docs 에 표시 안 함
#    .env 에 INTERNAL_API_KEY 를 설정해야 사용 가능 (없으면 모두 403)
# ══════════════════════════════════════════════
def require_internal_key(x_internal_key: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("INTERNAL_API_KEY", "")
    if not expected:
        raise ApiError(403, "INTERNAL_API_DISABLED", "INTERNAL_API_KEY 가 설정되지 않아 내부 API를 사용할 수 없습니다.")
    if not x_internal_key or not hmac.compare_digest(x_internal_key, expected):
        raise ApiError(403, "INVALID_INTERNAL_KEY", "내부 API 키가 올바르지 않습니다.")


internal = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_key)], include_in_schema=False)


@internal.post("/ingest", status_code=201, response_model=S.IngestLogOut)
def run_ingest(body: S.IngestRequest, db: DB):
    seller = db.get(User, body.seller_id)
    if seller is None or seller.status != UserStatus.ACTIVE:
        raise _not_found("SELLER", "셀러")
    try:
        log = ingest_csv(db, batch_name=body.batch_name, source_path=body.source_path, seller=seller)
    except IngestError as exc:
        db.rollback()
        raise ApiError(422, "INGEST_FAILED", str(exc)) from None
    return S.IngestLogOut.model_validate(log)


@internal.post("/analyze", response_model=S.AnalyzeResult)
def run_analyze(body: S.AnalyzeRequest, db: DB):
    count = analyze_pending(db, limit=body.limit, reanalyze_model_version=body.reanalyze_model_version)
    return S.AnalyzeResult(analyzed_count=count, model_version=MODEL_VERSION)


@internal.get("/ingest-logs", response_model=list[S.IngestLogOut])
def ingest_logs(db: DB):
    return [S.IngestLogOut.model_validate(x)
            for x in db.scalars(select(IngestLog).order_by(IngestLog.run_at.desc(), IngestLog.id.desc()).limit(100))]


router.include_router(internal)
