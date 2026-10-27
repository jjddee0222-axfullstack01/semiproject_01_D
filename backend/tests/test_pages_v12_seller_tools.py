"""v1.2 화면: 개선 조치·상세페이지 보완·불일치(상품별 대시보드), 메모(리뷰 목록), 응답 시간·처음 안내·샘플(대시보드),
리뷰 활용, 도움말, 엑셀 업로드, 개인정보 가리기"""
import io
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from sqlalchemy import func, select

import models as m
from tests.conftest import API, OTHER

pytestmark = pytest.mark.pages
D = lambda n: (date.today() - timedelta(days=n)).isoformat()
FIXTURE = Path(__file__).parent / "fixtures" / "platform_style_reviews.xlsx"


def make_xlsx(rows) -> bytes:
    """테스트용 최소 .xlsx (문자열은 sharedStrings, 숫자는 숫자 셀)"""
    strings, sheet_rows = [], []
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{chr(65 + ci)}{ri}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                strings.append(str(v))
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet_rows.append(f'<row r="{ri}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rns}><sheets><sheet name="s" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def upload(page, data: bytes, name: str):
    return page.post("/products/upload", files={"file": (name, data, "application/octet-stream")})


# ── 엑셀 · 쇼핑몰 파일 업로드 ───────────────────
def test_upload_xlsx_with_platform_headers(page, session):
    serial = (date.today() - timedelta(days=2) - date(1899, 12, 30)).days       # 엑셀 날짜 일련번호
    data = make_xlsx([["상품번호", "상품명", "구매자평점", "리뷰상세내용", "등록자", "리뷰등록일"],
                      [111, "엑셀상품", 5, "아주 좋아요 만족합니다", "kim***", serial],
                      [111, "엑셀상품", 1, "불량이에요 환불해주세요", "lee***", D(1).replace("-", ". ") + "."],
                      [111, "엑셀상품", 4.0, "좋아요", "park***", f"{date.today().year}년 1월 5일"]])
    r = upload(page, data, "smartstore.xlsx")
    assert "리뷰 3건 추가" in r.text and "위험 리뷰 1건이 있습니다" in r.text
    ratings = sorted(session.scalars(select(m.Review.rating).join(m.Review.product).where(m.Product.name == "엑셀상품")))
    assert ratings == [1, 4, 5]


def test_upload_real_excel_file(page, session):
    """openpyxl(엑셀 호환)로 만든 실제 .xlsx — 시트 이름·날짜 서식·여러 시트"""
    r = upload(page, FIXTURE.read_bytes(), "reviews_export.xlsx")
    assert "리뷰 3건 추가" in r.text
    product = session.scalar(select(m.Product).where(m.Product.name == "엑셀 텀블러"))
    assert product is not None and product.description in ("블랙", "화이트")
    assert {r.reviewed_at for r in product.reviews} == {date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)}


def test_upload_xlsx_missing_columns(page):
    r = upload(page, make_xlsx([["상품명", "평점"], ["A", 5]]), "x.xlsx")
    assert "필수 컬럼이 없습니다" in r.text


def test_header_aliases_ignore_spaces_and_brackets():
    from pipeline import _normalize_header
    assert _normalize_header("리뷰 상세 내용") == "content"
    assert _normalize_header("평점(1~5)") == "rating"
    assert _normalize_header("리뷰 등록일") == "reviewed_at"


# ── 상품별 대시보드 ────────────────────────────
def test_product_dashboard_actions(page, ids, session):
    url = f"/products/{ids['product_a']}"
    text = page.get(url).text
    assert 'id="actions"' in text and "개선 조치 기록" in text and 'id="detail-tips"' in text
    r = page.post(f"{url}/actions", data={"action_date": D(3), "title": "검수 강화", "issue": "PRODUCT"})
    assert "기록했습니다" in r.text and "조치 전 4일" in r.text and "'상품 품질' 비율" in r.text
    action = session.scalar(select(m.ProductAction))
    assert action.issue_type == m.IssueType.PRODUCT
    chart = r.text.split("PP.monthlyCount")[1]                                   # 차트 표시선 (JSON 은 \u 이스케이프)
    assert '"label": "\\uac80\\uc218 \\uac15\\ud654"' in chart and f'"month": "{D(3)[:7]}"' in chart
    r = page.post(f"{url}/actions", data={"action_date": "어제", "title": "x"})
    assert "YYYY-MM-DD" in r.text
    r = page.post(f"{url}/actions", data={"action_date": D(0), "title": ""})
    assert "조치 내용을 입력해 주세요" in r.text
    r = page.post(f"{url}/actions/{action.id}/delete")
    assert "삭제했습니다" in r.text and session.scalar(select(func.count()).select_from(m.ProductAction)) == 0


def test_product_actions_ownership(page, other_api, ids, session):
    page.post(f"/products/{ids['product_a']}/actions", data={"action_date": D(0), "title": "a"})
    aid = session.scalar(select(m.ProductAction.id))
    assert other_api.post(f"/products/{ids['product_a']}/actions", data={"action_date": D(0), "title": "x"}).status_code == 404
    assert other_api.post(f"/products/{ids['product_a']}/actions/{aid}/delete").status_code == 404
    assert page.post(f"/products/{ids['product_b']}/actions/{aid}/delete").status_code == 404     # 다른 상품 경로


def test_mismatch_link_and_filter(page, api, ids):
    api.post(f"{API}/reviews", json={"product_id": ids["product_a"], "rating": 5, "content": "디자인은 예쁜데 다만 냄새가 나요"})
    text = page.get(f"/products/{ids['product_a']}").text
    assert "별점은 4~5점인데 아쉬움·불만이 섞인 리뷰가 <b>1건</b>" in text
    r = page.get(f"/reviews?product_id={ids['product_a']}&mismatch=1")
    assert "다만 냄새가 나요" in r.text and "배송이 정말 빠르고" not in r.text and "별점·내용 불일치</span>" in r.text


# ── 리뷰 목록 메모 ─────────────────────────────
def test_review_memo_page(page, ids, session):
    rid = ids["risky_a"]
    back = "/reviews?risk=1"
    r = page.post(f"/reviews/{rid}/memo", data={"status": "IN_PROGRESS", "memo": "교환 접수\n내일 발송", "next": back})
    assert r.url.path == "/reviews" and "risk=1" in str(r.url)
    assert "처리 중" in r.text and "교환 접수\n내일 발송" in r.text
    assert "불량품이 왔어요" in page.get("/reviews?memo=IN_PROGRESS").text
    assert "불량품이 왔어요" not in page.get("/reviews?memo=NONE").text
    assert "불량품이 왔어요" not in page.get("/reviews?memo=DONE").text
    memo = session.get(m.ReviewMemo, rid)
    assert memo.status == m.MemoStatus.IN_PROGRESS and memo.updated_by is not None
    r = page.post(f"/reviews/{rid}/memo/delete", data={"next": back})
    assert "메모를 지웠습니다" in r.text


def test_review_memo_validation_and_safety(page, other_api, ids):
    rid = ids["risky_a"]
    r = page.post(f"/reviews/{rid}/memo", data={"status": "BAD"})
    assert "처리 상태를 선택해 주세요" in r.text
    r = page.post(f"/reviews/{rid}/memo", data={"status": "DONE", "memo": "가" * 1001})
    assert "1,000자 이하" in r.text
    r = page.post(f"/reviews/{rid}/memo", data={"status": "DONE", "next": "https://evil.example/x"}, follow_redirects=False)
    assert r.headers["location"].startswith("http://testserver/reviews")            # 외부 주소로 보내지 않음
    assert other_api.post(f"/reviews/{rid}/memo", data={"status": "DONE"}).status_code == 404


def test_blinded_tab_has_report_export(page, ids):
    page.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": "비방"})
    assert "/api/v1/exports/blinded-reviews.csv" in page.get("/reviews?status=BLINDED").text
    assert "/api/v1/exports/blinded-reviews.csv" not in page.get("/reviews").text


# ── 대시보드 ──────────────────────────────────
def test_dashboard_response_card(page):
    text = page.get("/dashboard").text
    assert "답글 응답 시간" in text and "아직 단 답글이 없습니다" in text and "3일 넘게 방치된 위험 리뷰가 없습니다" in text
    assert "/help#risk" in text and "시작하기" not in text                         # 상품이 있으면 안내 숨김


def test_onboarding_and_sample(client, session):
    assert client.post(f"{API}/auth/signup", json=OTHER).status_code == 201
    client.post("/login", data={"email": OTHER["email"], "password": OTHER["password"]})
    text = client.get("/dashboard").text
    assert "PIN POINT REVIEW 시작하기" in text and "샘플 데이터로 먼저 체험하기" in text
    r = client.post("/onboarding/sample")
    assert "샘플 리뷰 17건을 넣었습니다" in r.text and "샘플 데이터 지우기" in r.text and "시작하기" not in r.text
    assert "샘플 데이터가 이미 들어 있습니다" in client.post("/onboarding/sample").text
    assert "[샘플] 보온 텀블러 500ml" in client.get("/products").text
    assert "010-****-****" in client.get("/reviews?q=연락처").text                 # 샘플 속 전화번호 가림
    assert "sample" not in client.get("/products/uploads").text.lower()
    r = client.post("/onboarding/sample/delete")
    assert "샘플 상품 3개와 리뷰를 모두 지웠습니다" in r.text and "시작하기" in r.text
    other = session.scalar(select(m.User).where(m.User.email == OTHER["email"]))
    assert session.scalar(select(func.count()).select_from(m.Product).where(m.Product.seller_id == other.id)) == 0


def test_sample_delete_keeps_real_products(page, session):
    page.post("/onboarding/sample")
    page.post("/onboarding/sample/delete")
    assert session.scalar(select(func.count()).select_from(m.Product)) == 3                     # 데모 상품 유지


# ── 리뷰 활용 · 도움말 · 사이드바 · 리포트 ─────────
def test_marketing_page(page, ids, other_api):
    text = page.get("/marketing").text
    assert "리뷰 활용" in text and "베스트 리뷰" in text and "강점 키워드" in text and "복사" in text
    assert "빠르고 안전한 배송" in text and "최**" in text and "최유리" not in text
    text = page.get(f"/marketing?product_id={ids['product_c']}").text
    assert "가성비 최고입니다" in text and "배송도 빠르고 상품 상태가" not in text
    assert "프리미엄" not in other_api.get(f"/marketing?product_id={ids['product_a']}").text      # 남의 상품 → 내 전체(빈)


def test_help_page_and_sidebar(page):
    text = page.get("/help").text
    for anchor in ('id="risk"', 'id="surge"', 'id="mismatch"', 'id="response"', 'id="upload"', 'id="privacy"'):
        assert anchor in text, anchor
    assert "<b>2 이상</b>" in text and "<b>3건 이상</b>" in text and "{고객명}" in text
    side = page.get("/dashboard").text
    assert '/marketing">리뷰 활용</a>' in side and '/help">도움말</a>' in side


def test_help_requires_login(client):
    assert "/login" in client.get("/help", follow_redirects=False).headers["location"]


def test_reports_have_response_time_kpi(page):
    assert "평균 답글 시간" in page.get("/reports").text


def test_pii_masked_on_pages(page, api, ids):
    api.post(f"{API}/reviews", json={"product_id": ids["product_a"], "rating": 1, "content": "환불해주세요 010-5555-6666"})
    for url in ("/dashboard", "/reviews", f"/products/{ids['product_a']}", "/cschatbot", "/reports", "/analysis"):
        text = page.get(url).text
        assert "5555-6666" not in text, url
