"""
PIN POINT REVIEW - 데이터 파이프라인 (US-09 적재 / US-10 클리닝 / US-11 분석)

CSV 형식 (UTF-8, 첫 줄은 헤더)
    필수: product_name, rating, content, reviewed_at(YYYY-MM-DD 또는 YYYY.MM.DD)
    선택: category, product_description, reviewer_name

  - 결측(필수값 없음)·형식 오류 행은 건너뛰고 missing_count 로 기록
  - 같은 상품·작성자·작성일·본문 리뷰는 중복으로 보고 duplicate_count 로 기록 (DB·같은 파일 모두 확인)
  - 원문은 content_raw, 정제본은 content_clean 에 분리 저장 → 분석 결과는 review_analysis
"""
import csv
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

try:
    from .database import analyze_and_save, seller_risk_keywords
    from .models import IngestLog, Product, Review, ReviewAnalysis, User
except ImportError:
    from database import analyze_and_save, seller_risk_keywords
    from models import IngestLog, Product, Review, ReviewAnalysis, User

REQUIRED_COLUMNS = ("product_name", "rating", "content", "reviewed_at")


class IngestError(ValueError):
    """적재를 시작할 수 없는 오류 (파일 없음, 필수 컬럼 없음 등)"""


def _parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_rating(value: str) -> Optional[int]:
    try:
        rating = int(float((value or "").strip()))
    except ValueError:
        return None
    return rating if 1 <= rating <= 5 else None


def ingest_csv(db: Session, *, batch_name: str, source_path: str, seller: User) -> IngestLog:
    path = Path(source_path)
    if not path.is_file():
        raise IngestError(f"파일을 찾을 수 없습니다: {source_path}")

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing_cols:
            raise IngestError(f"CSV에 필수 컬럼이 없습니다: {', '.join(missing_cols)}")
        rows = list(reader)

    log = IngestLog(batch_name=batch_name, total_count=len(rows), duplicate_count=0, missing_count=0)
    risk_keywords = seller_risk_keywords(db, seller.id)
    products: dict[str, Product] = {p.name: p for p in db.scalars(select(Product).where(Product.seller_id == seller.id))}
    seen: set[tuple] = set()

    for row in rows:
        name = (row.get("product_name") or "").strip()
        content = (row.get("content") or "").strip()
        rating = _parse_rating(row.get("rating"))
        reviewed_at = _parse_date(row.get("reviewed_at"))
        if not name or not content or rating is None or reviewed_at is None:
            log.missing_count += 1
            continue

        reviewer = (row.get("reviewer_name") or "").strip()[:50] or None
        product = products.get(name)
        if product is None:
            product = Product(seller=seller, name=name[:255],
                              category=(row.get("category") or "").strip()[:100] or None,
                              description=(row.get("product_description") or "").strip() or None)
            db.add(product)
            db.flush()
            products[name] = product

        key = (product.id, reviewer, reviewed_at, content)
        exists = key in seen or db.scalar(
            select(Review.id).where(Review.product_id == product.id, Review.reviewed_at == reviewed_at,
                                    Review.content_raw == content,
                                    Review.reviewer_name.is_(None) if reviewer is None
                                    else Review.reviewer_name == reviewer).limit(1))
        if exists:
            log.duplicate_count += 1
            continue
        seen.add(key)

        review = Review(product=product, reviewer_name=reviewer, rating=rating,
                        content_raw=content, reviewed_at=reviewed_at)
        db.add(review)
        analyze_and_save(db, review, risk_keywords)

    db.add(log)
    db.commit()
    return log


def analyze_pending(db: Session, *, limit: int, reanalyze_model_version: Optional[str] = None) -> int:
    """분석 결과가 없는 리뷰(+ 지정한 model_version 으로 분석된 리뷰)를 분석"""
    condition = ReviewAnalysis.id.is_(None)
    if reanalyze_model_version:
        condition = or_(condition, ReviewAnalysis.model_version == reanalyze_model_version)
    reviews = db.scalars(
        select(Review).outerjoin(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
        .where(condition).order_by(Review.id).limit(limit)
    ).all()

    cache: dict[int, list[tuple[str, int]]] = {}
    for review in reviews:
        seller_id = review.product.seller_id
        if seller_id not in cache:
            cache[seller_id] = seller_risk_keywords(db, seller_id)
        analyze_and_save(db, review, cache[seller_id])
    db.commit()
    return len(reviews)
