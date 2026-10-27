"""HTML 화면 테스트 — 상품 조회 화면의 리뷰 CSV 업로드"""
import pytest
from sqlalchemy import func, select

import models as m

pytestmark = pytest.mark.pages

KOREAN_CSV = ("상품명,카테고리,작성자,평점,리뷰내용,작성일\n"
              "새 텀블러,주방,김민수,5,보온이 오래가고 예뻐요.,2026-10-01\n"
              "새 텀블러,주방,이지은,1,뚜껑이 헐거워서 물이 새요. 환불 원합니다.,2026.10.03\n"
              "[상품명] 프리미엄 시그니처 상품 A,,박서준,4,생각보다 튼튼해요.,2026/10/05\n")


def upload(client, content, filename="reviews.csv", encoding="utf-8"):
    data = content.encode(encoding) if isinstance(content, str) else content
    return client.post("/products/upload", files={"file": (filename, data, "text/csv")})


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_products_page_has_upload_form(page):
    r = page.get("/products")
    assert 'enctype="multipart/form-data"' in r.text and 'name="file"' in r.text
    assert "/products/upload-template.csv" in r.text


def test_upload_korean_headers_creates_products_and_analyzes(page, session):
    before = count(session, m.Review)
    r = upload(page, KOREAN_CSV)
    assert r.url.path == "/products" and "리뷰 3건 추가" in r.text
    assert count(session, m.Review) == before + 3
    assert "새 텀블러" in r.text                                    # 새 상품이 목록에 표시
    product = session.scalar(select(m.Product).where(m.Product.name == "새 텀블러"))
    assert product.category == "주방" and len(product.reviews) == 2
    refund = next(rv for rv in product.reviews if rv.rating == 1)
    assert refund.analysis.severity >= 2 and refund.content_clean       # 바로 분석됨
    assert refund.reviewed_at.isoformat() == "2026-10-03"
    log = session.scalar(select(m.IngestLog).order_by(m.IngestLog.id.desc()))
    assert log.total_count == 3 and log.batch_name.endswith("reviews.csv")


def test_upload_same_file_twice_skips_duplicates(page, session):
    upload(page, KOREAN_CSV)
    before = count(session, m.Review)
    r = upload(page, KOREAN_CSV)
    assert "리뷰 0건 추가, 중복 3건 제외" in r.text and count(session, m.Review) == before


def test_upload_english_headers_and_cp949(page, session):
    csv_text = ("product_name,rating,content,reviewed_at,reviewer_name\n"
                "엑셀 상품,3,그냥 그래요,2026-09-30,최유리\n")
    r = upload(page, csv_text, encoding="cp949")                    # 엑셀 'CSV' 저장 형식
    assert "리뷰 1건 추가" in r.text
    assert session.scalar(select(m.Review).where(m.Review.content_raw == "그냥 그래요")).reviewer_name == "최유리"


def test_upload_reports_bad_rows(page, session):
    csv_text = ("상품명,평점,리뷰내용,작성일\n"
                "A상품,5,좋아요,2026-10-01\n"
                ",5,상품명 없음,2026-10-01\n"
                "A상품,9,평점 오류,2026-10-01\n"
                "A상품,4,,2026-10-01\n"
                "A상품,4,날짜 오류,어제\n")
    r = upload(page, csv_text)
    assert "리뷰 1건 추가, 오류 4건 건너뜀" in r.text
    for text in ("3행(상품명 없음)", "4행(평점은 1~5 정수)", "5행(리뷰내용 없음)", "6행(작성일 형식 오류)"):
        assert text in r.text, text


@pytest.mark.parametrize("filename, content, message", [
    ("reviews.txt", "x", "CSV(.csv) 또는 엑셀(.xlsx) 파일만"),               # v1.2: .xlsx 허용으로 문구 변경
    ("reviews.xls", "x", "예전 엑셀 형식(.xls)은 읽을 수 없습니다"),
    ("reviews.xlsx", "x", "엑셀 파일을 읽을 수 없습니다"),                   # 확장자만 .xlsx 인 깨진 파일
    ("reviews.csv", "상품명,평점\nA,5\n", "필수 컬럼이 없습니다: 리뷰내용(content), 작성일(reviewed_at)"),
    ("reviews.csv", "", "빈 파일입니다"),
    ("reviews.csv", "상품명,평점,리뷰내용,작성일\n", "리뷰 데이터가 없습니다"),
    ("reviews.csv", b"\xff\xfe\x00\xd8broken", "인코딩"),
])
def test_upload_rejects_bad_files(page, session, filename, content, message):
    before = count(session, m.Review)
    r = upload(page, content, filename=filename)
    assert message in r.text and count(session, m.Review) == before


def test_upload_without_file(page):
    r = page.post("/products/upload", data={})
    assert "CSV 또는 엑셀(.xlsx) 파일을 선택해 주세요" in r.text


def test_upload_too_large(page, monkeypatch):
    import main
    monkeypatch.setattr(main, "UPLOAD_MAX_BYTES", 100)
    r = upload(page, KOREAN_CSV * 5)
    assert "파일이 너무 큽니다" in r.text


def test_upload_goes_to_own_account_only(page, other_api, session):
    upload(other_api, KOREAN_CSV)
    other = session.scalar(select(m.User).where(m.User.email == "other@shop.kr"))
    names = session.scalars(select(m.Product.name).where(m.Product.seller_id == other.id)).all()
    assert sorted(names) == ["[상품명] 프리미엄 시그니처 상품 A", "새 텀블러"]   # 데모 셀러 상품과 섞이지 않음
    assert "새 텀블러" not in page.get("/products").text


def test_upload_requires_login(client):
    r = upload(client, KOREAN_CSV)
    assert r.url.path == "/login"


def test_template_download(page):
    r = page.get("/products/upload-template.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.content.startswith(b"\xef\xbb\xbf") and "상품명,카테고리,작성자,평점,리뷰내용,작성일" in r.text
    # 양식 그대로 올리면 2건 적재
    assert "리뷰 2건 추가" in upload(page, r.content).text
