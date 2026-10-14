"""
PIN POINT REVIEW - 데이터 파이프라인 (US-09 적재 / US-10 클리닝 / US-11 분석)

CSV 형식 (UTF-8 또는 엑셀 한글 CP949, 첫 줄은 헤더)
    필수: product_name(상품명), rating(평점), content(리뷰내용), reviewed_at(작성일, YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD)
    선택: category(카테고리), product_description(상품설명), reviewer_name(작성자)
    ※ 헤더는 영어·한글 모두 가능 (HEADER_ALIASES)

사용처
  - 상품 조회 화면의 CSV 업로드 (ingest_upload)  → 로그인한 셀러의 상품으로 적재
  - 내부 API /api/v1/internal/ingest (ingest_csv) → 서버에 있는 파일 경로로 적재

  - 결측(필수값 없음)·형식 오류 행은 건너뛰고 missing_count 로 기록
  - 같은 상품·작성자·작성일·본문 리뷰는 중복으로 보고 duplicate_count 로 기록 (DB·같은 파일 모두 확인)
  - 원문은 content_raw, 정제본은 content_clean 에 분리 저장 → 분석 결과는 review_analysis
"""
import csv
import io
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
COLUMN_LABELS = {"product_name": "상품명", "rating": "평점", "content": "리뷰내용", "reviewed_at": "작성일"}

# 한글 헤더(엑셀에서 만든 파일) → 내부 컬럼 이름
HEADER_ALIASES = {
    "product_name": ("상품명", "상품", "상품 이름", "상품이름"),
    "category": ("카테고리", "분류"),
    "product_description": ("상품설명", "상품 설명"),
    "reviewer_name": ("작성자", "리뷰어", "구매자", "작성자명"),
    "rating": ("평점", "별점"),
    "content": ("리뷰내용", "리뷰 내용", "리뷰", "내용", "본문"),
    "reviewed_at": ("작성일", "작성일자", "리뷰일", "날짜"),
}
_ALIAS_TO_COLUMN = {alias: col for col, aliases in HEADER_ALIASES.items() for alias in (col, *aliases)}


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


def _normalize_header(name: Optional[str]) -> str:
    name = (name or "").strip().lstrip("\ufeff")
    return _ALIAS_TO_COLUMN.get(name, _ALIAS_TO_COLUMN.get(name.lower(), name.lower()))


def parse_csv_text(text: str) -> list[dict]:
    """CSV 문자열 → 행 목록 (헤더를 내부 컬럼 이름으로 맞춤). 필수 컬럼이 없으면 IngestError"""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        raise IngestError("빈 파일입니다. 첫 줄에 헤더(상품명, 평점, 리뷰내용, 작성일 …)가 있어야 합니다.")
    columns = [_normalize_header(h) for h in header]
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing_cols:
        raise IngestError("CSV에 필수 컬럼이 없습니다: "
                          + ", ".join(f"{COLUMN_LABELS[c]}({c})" for c in missing_cols))
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):          # 완전히 빈 줄은 무시
            continue
        rows.append(dict(zip(columns, values)))
    return rows


def decode_csv_bytes(data: bytes) -> str:
    """업로드 파일 → 문자열. UTF-8(BOM 포함) 먼저, 안 되면 엑셀 한글(CP949)"""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("파일 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949(엑셀 한글) CSV로 저장해 주세요.")


def ingest_rows(db: Session, *, batch_name: str, rows: list[dict], seller: User) -> tuple[IngestLog, list[str]]:
    """행 목록을 적재 → (적재 로그, 건너뛴 행 설명 목록). 커밋까지 수행

    - 결측(필수값 없음)·형식 오류 행은 건너뛰고 missing_count
    - 같은 상품·작성자·작성일·본문 리뷰는 중복으로 보고 duplicate_count (DB·같은 파일 모두 확인)
    - 행 번호는 헤더를 1행으로 센 엑셀 기준
    """
    log = IngestLog(batch_name=batch_name[:255], total_count=len(rows), duplicate_count=0, missing_count=0)
    problems: list[str] = []
    risk_keywords = seller_risk_keywords(db, seller.id)
    products: dict[str, Product] = {p.name: p for p in db.scalars(select(Product).where(Product.seller_id == seller.id))}
    seen: set[tuple] = set()

    for line_no, row in enumerate(rows, start=2):
        name = (row.get("product_name") or "").strip()
        content = (row.get("content") or "").strip()
        rating = _parse_rating(row.get("rating"))
        reviewed_at = _parse_date(row.get("reviewed_at"))
        reason = ("상품명 없음" if not name else "리뷰내용 없음" if not content
                  else "평점은 1~5" if rating is None else "작성일 형식 오류" if reviewed_at is None else None)
        if reason:
            log.missing_count += 1
            problems.append(f"{line_no}행({reason})")
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
    return log, problems


def ingest_csv(db: Session, *, batch_name: str, source_path: str, seller: User) -> IngestLog:
    """서버에 있는 CSV 파일을 적재 (내부 API 용)"""
    path = Path(source_path)
    if not path.is_file():
        raise IngestError(f"파일을 찾을 수 없습니다: {source_path}")
    rows = parse_csv_text(decode_csv_bytes(path.read_bytes()))
    log, _ = ingest_rows(db, batch_name=batch_name, rows=rows, seller=seller)
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
