"""
PIN POINT REVIEW - 데이터 파이프라인 (US-09 적재 / US-10 클리닝 / US-11 분석)

CSV 형식 (UTF-8 또는 엑셀 한글 CP949, 첫 줄은 헤더) — v1.2: 엑셀 .xlsx 도 가능 (parse_xlsx_bytes, 첫 시트)
    필수: product_name(상품명), rating(평점), content(리뷰내용), reviewed_at(작성일, YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD)
    선택: category(카테고리), product_description(상품설명), reviewer_name(작성자)
    ※ 헤더는 영어·한글 모두 가능 (HEADER_ALIASES)
    ※ v1.2: 스마트스토어·쿠팡 등에서 내려받은 리뷰 파일의 열 이름도 HEADER_ALIASES 에 추가
       (구매자평점·리뷰상세내용·리뷰등록일·등록자 …). 쇼핑몰마다 열 이름이 바뀔 수 있어 실제 파일로 확인 필요

사용처
  - 상품 조회 화면의 CSV 업로드 (ingest_upload)  → 로그인한 셀러의 상품으로 적재
  - 내부 API /api/v1/internal/ingest (ingest_csv) → 서버에 있는 파일 경로로 적재

  - 결측(필수값 없음)·형식 오류 행은 건너뛰고 missing_count 로 기록
  - 같은 상품·작성자·작성일·본문 리뷰는 중복으로 보고 duplicate_count 로 기록 (DB·같은 파일 모두 확인)
  - 원문은 content_raw, 정제본은 content_clean 에 분리 저장 → 분석 결과는 review_analysis
"""
import csv
import io
import re
import zipfile
from xml.etree import ElementTree
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

try:
    from .database import analyze_and_save, reanalyze_reviews, seller_risk_keywords
    from .models import IngestLog, Product, Review, ReviewAnalysis, User
except ImportError:
    from database import analyze_and_save, reanalyze_reviews, seller_risk_keywords
    from models import IngestLog, Product, Review, ReviewAnalysis, User

REQUIRED_COLUMNS = ("product_name", "rating", "content", "reviewed_at")
COLUMN_LABELS = {"product_name": "상품명", "rating": "평점", "content": "리뷰내용", "reviewed_at": "작성일"}

# 한글 헤더(엑셀에서 만든 파일) → 내부 컬럼 이름
HEADER_ALIASES = {
    "product_name": ("상품명", "상품", "상품 이름", "상품이름", "노출상품명", "등록상품명", "판매상품명"),
    "category": ("카테고리", "분류", "카테고리명"),
    "product_description": ("상품설명", "상품 설명", "옵션", "옵션정보", "옵션명", "구매옵션"),
    "reviewer_name": ("작성자", "리뷰어", "구매자", "작성자명", "등록자", "구매자명", "구매자ID", "작성자ID",
                      "아이디", "닉네임"),
    "rating": ("평점", "별점", "구매자평점", "리뷰평점", "리뷰 평점", "상품평점", "만족도", "평가점수", "별점점수"),
    "content": ("리뷰내용", "리뷰 내용", "리뷰", "내용", "본문", "리뷰상세내용", "리뷰 상세내용", "상품평",
                "상품평 내용", "리뷰본문", "후기", "후기내용"),
    "reviewed_at": ("작성일", "작성일자", "리뷰일", "날짜", "리뷰등록일", "리뷰 등록일", "등록일", "등록일자",
                    "등록일시", "작성일시", "리뷰작성일", "리뷰 작성일"),
}
# 공백·괄호 설명을 뺀 이름으로도 찾음 ('리뷰 상세 내용', '평점(1~5)' → '리뷰상세내용', '평점')
_ALIAS_TO_COLUMN = {re.sub(r"\s+", "", alias): col
                    for col, aliases in HEADER_ALIASES.items() for alias in (col, *aliases)}


class IngestError(ValueError):
    """적재를 시작할 수 없는 오류 (파일 없음, 필수 컬럼 없음 등)"""


_LOOSE_DATE = re.compile(r"^(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def _parse_date(value: str) -> Optional[date]:
    """'2026-10-01' · '2026.10.01' · '2026/10/01' (+ 시각) · v1.2: '2026. 10. 1.' · '2026년 10월 1일' · 엑셀 날짜 숫자"""
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    if m := _LOOSE_DATE.match(value):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if re.fullmatch(r"\d{5}(\.\d+)?", value):          # 엑셀 날짜 일련번호 (1900 날짜 체계)
        serial = int(float(value))
        if 20000 < serial < 80000:
            return date(1899, 12, 30) + timedelta(days=serial)
    return None


def _parse_rating(value: str) -> Optional[int]:
    """평점은 1~5 정수만. '5' · '5.0' 은 허용, '4.5' 처럼 소수점이 있으면 None (예전에는 4 로 잘라서 저장했음)"""
    try:
        number = float((value or "").strip())
    except ValueError:
        return None
    if not number.is_integer():
        return None
    rating = int(number)
    return rating if 1 <= rating <= 5 else None


# DB 컬럼 크기 (models.py 와 같게): 넘으면 잘라서 저장하지 않고 오류 행으로 안내
PRODUCT_NAME_MAX = 255                 # products.name VARCHAR(255)
REVIEW_CONTENT_MAX_BYTES = 65_535      # reviews.content_raw TEXT (MariaDB TEXT 최대 65,535 바이트)


def _row_problem(name: str, content: str, rating: Optional[int], reviewed_at: Optional[date]) -> Optional[str]:
    """행 검증 → 문제가 있으면 사용자에게 보여 줄 이유, 없으면 None"""
    if not name:
        return "상품명 없음"
    if len(name) > PRODUCT_NAME_MAX:
        return f"상품명 {PRODUCT_NAME_MAX}자 초과"
    if not content:
        return "리뷰내용 없음"
    if len(content.encode("utf-8")) > REVIEW_CONTENT_MAX_BYTES:
        return "리뷰내용이 너무 김"
    if rating is None:
        return "평점은 1~5 정수"
    if reviewed_at is None:
        return "작성일 형식 오류"
    if reviewed_at > date.today():
        return "작성일이 미래"
    return None


def _normalize_header(name: Optional[str]) -> str:
    name = (name or "").strip().lstrip("\ufeff")
    key = re.sub(r"\s+", "", re.sub(r"\(.*?\)|\[.*?\]", "", name))      # 공백·괄호 설명 제거
    for candidate in (name, key, name.lower(), key.lower()):
        if candidate in _ALIAS_TO_COLUMN:
            return _ALIAS_TO_COLUMN[candidate]
    return name.lower()


def parse_csv_text(text: str) -> list[dict]:
    """CSV 문자열 → 행 목록 (헤더를 내부 컬럼 이름으로 맞춤). 필수 컬럼이 없으면 IngestError"""
    return parse_table(csv.reader(io.StringIO(text)))


def parse_table(reader) -> list[dict]:
    """행(문자열 목록)들 → 행 목록. 첫 행은 헤더 (CSV·엑셀 공용)"""
    reader = iter(reader)
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


# ──────────────────────────────────────────────
# v1.2 엑셀(.xlsx) 읽기 — 새 라이브러리 없이 표준 zipfile + XML 로 첫 번째 시트만 읽음
#   (.xlsx = 압축 파일 안의 XML. 문자열은 sharedStrings.xml, 셀 값은 sheet1.xml)
# ──────────────────────────────────────────────
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
XLSX_MAX_UNCOMPRESSED = 50 * 1024 * 1024        # 압축 폭탄 방지 (풀었을 때 50MB 까지)


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _first_sheet_path(zf: zipfile.ZipFile) -> str:
    """workbook.xml 의 첫 번째 시트 → 실제 파일 경로 (보통 xl/worksheets/sheet1.xml)"""
    try:
        wb = ElementTree.fromstring(zf.read("xl/workbook.xml"))
        rid = wb.find("m:sheets/m:sheet", _NS).get(f"{{{_NS['r']}}}id")
        rels = ElementTree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels.findall("rel:Relationship", _NS) if r.get("Id") == rid)
        target = target.lstrip("/")
        return target if target.startswith("xl/") else "xl/" + target
    except (KeyError, AttributeError, StopIteration, ElementTree.ParseError):
        return "xl/worksheets/sheet1.xml"


def parse_xlsx_bytes(data: bytes) -> list[dict]:
    """엑셀 .xlsx → 행 목록 (parse_csv_text 와 같은 형식). 날짜 셀은 일련번호 → _parse_date 가 변환"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise IngestError("엑셀 파일을 읽을 수 없습니다. 예전 형식(.xls)이라면 엑셀에서 '.xlsx'로 다시 저장해 주세요.")
    with zf:
        if sum(i.file_size for i in zf.infolist()) > XLSX_MAX_UNCOMPRESSED:
            raise IngestError("엑셀 파일 내용이 너무 큽니다. 나눠서 올려 주세요.")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            for si in ElementTree.fromstring(zf.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        try:
            sheet = ElementTree.fromstring(zf.read(_first_sheet_path(zf)))
        except (KeyError, ElementTree.ParseError):
            raise IngestError("엑셀 파일에서 시트를 찾을 수 없습니다.")

    rows: list[list[str]] = []
    for row in sheet.iter(f"{{{_NS['m']}}}row"):
        values: dict[int, str] = {}
        for c in row.findall("m:c", _NS):
            kind, v = c.get("t"), c.find("m:v", _NS)
            if kind == "s" and v is not None:
                text = shared[int(v.text)] if v.text and v.text.isdigit() and int(v.text) < len(shared) else ""
            elif kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            else:
                text = v.text if v is not None and v.text else ""
                if re.fullmatch(r"-?\d+\.0+", text):
                    text = text.split(".")[0]          # 5.0 → 5
            values[_col_index(c.get("r", "A1"))] = text
        if values:
            rows.append([values.get(i, "") for i in range(max(values) + 1)])
    return parse_table(rows)


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
        reason = _row_problem(name, content, rating, reviewed_at)
        if reason:
            log.missing_count += 1
            problems.append(f"{line_no}행({reason})")
            continue

        reviewer = (row.get("reviewer_name") or "").strip()[:50] or None
        product = products.get(name)
        if product is None:
            product = Product(seller=seller, name=name,
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
        .options(selectinload(Review.analysis), selectinload(Review.keyword_links), selectinload(Review.product))
    ).all()
    count = reanalyze_reviews(db, reviews)
    db.commit()
    return count
