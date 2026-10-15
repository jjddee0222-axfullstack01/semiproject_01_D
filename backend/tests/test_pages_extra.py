"""HTML 화면 테스트 — 리뷰 목록 · 업로드 이력 · 상품 비교 · 대시보드 처리할 일 · 모바일 메뉴"""
import pytest
from sqlalchemy import select

import models as m

pytestmark = pytest.mark.pages

CSV = "상품명,평점,리뷰내용,작성일\n새 상품,1,불량이에요 환불해주세요,2026-10-01\n새 상품,5,좋아요,2026-10-02\n,5,x,2026-10-02\n"


def rows(html: str) -> int:
    return html.count('<div class="review-row')


# ── 리뷰 목록
def test_review_list_all(page):
    r = page.get("/reviews")
    assert r.status_code == 200 and "리뷰 목록" in r.text
    assert rows(r.text) == 11 and "조건에 맞는 리뷰 <b>11</b>건" in r.text
    assert 'class="menu-item active"><a href="http://testserver/reviews"' in r.text


@pytest.mark.parametrize("query, count", [
    ("sentiment=NEG", 3), ("sentiment=POS", 5), ("sentiment=NEU", 3), ("risk=1", 3), ("rating=5", 4),
    ("q=배송", 3), ("issue=PACKAGING", 1), ("period=7", 6), ("replied=yes", 0), ("replied=no", 11),
    ("sentiment=NEG&risk=1", 3), ("sentiment=bogus", 11), ("q=%25", 0),
])
def test_review_list_filters(page, query, count):
    assert rows(page.get(f"/reviews?{query}").text) == count, query


def test_review_list_product_filter_and_sort(page, ids):
    r = page.get(f"/reviews?product_id={ids['product_b']}&sort=rating_low")
    assert rows(r.text) == 3
    first = r.text.split('<div class="review-row')[1]
    assert "★ 1" in first                                               # 평점 낮은 순


def test_review_list_ignores_other_sellers_product(other_api, ids):
    r = other_api.get(f"/reviews?product_id={ids['product_a']}")
    assert rows(r.text) == 0 and "아직 등록된 리뷰가 없습니다" in r.text


def test_review_list_replied_and_blinded(page, ids):
    page.post(f"/api/v1/reviews/{ids['risky_a']}/replies", json={"content": "죄송합니다"})
    assert rows(page.get("/reviews?replied=yes").text) == 1
    assert "답글 1" in page.get("/reviews?replied=yes").text
    page.post(f"/reviews/{ids['positive_a']}/blind", data={"reason": "광고성"})
    assert rows(page.get("/reviews").text) == 10
    r = page.get("/reviews?status=BLINDED")
    assert rows(r.text) == 1 and "사유: 광고성" in r.text


def test_review_list_pagination(page):
    lines = "\n".join(f"페이지 상품,4,리뷰 내용 {i},2026-09-{i % 28 + 1:02d}" for i in range(30))
    page.post("/products/upload", files={"file": ("p.csv", ("상품명,평점,리뷰내용,작성일\n" + lines).encode(), "text/csv")})
    r = page.get("/reviews")
    assert rows(r.text) == 20 and "1 / 3 페이지" in r.text and "다음 &rarr;" in r.text
    assert rows(page.get("/reviews?page=3").text) == 1
    assert "1 / 3 페이지" in page.get("/reviews?page=abc").text


# ── 업로드 이력
def test_upload_history(page, other_api):
    assert "아직 업로드한 CSV가 없습니다" in page.get("/products/uploads").text
    page.post("/products/upload", files={"file": ("first.csv", CSV.encode(), "text/csv")})
    page.post("/products/upload", files={"file": ("second.csv", CSV.encode(), "text/csv")})
    r = page.get("/products/uploads")
    assert "first.csv" in r.text and "second.csv" in r.text and "2회" in r.text
    assert r.text.index("second.csv") < r.text.index("first.csv")        # 최신순
    # 합계: 추가 2(첫 파일) · 중복 2(두 번째 파일) · 오류 2(파일마다 1행)
    assert 'value ok">2건' in r.text and 'value warn">2건' in r.text and 'value bad">2건' in r.text
    assert "first.csv" not in other_api.get("/products/uploads").text   # 남의 기록은 안 보임


def test_products_page_links(page):
    text = page.get("/products").text
    assert "/products/uploads" in text and "/compare" in text


# ── 상품 비교
def test_compare_defaults_to_first_two(page):
    r = page.get("/compare")
    assert r.status_code == 200 and "상품 비교" in r.text and "한눈에 보는 차이" in r.text
    assert "프리미엄 시그니처 상품 A" in r.text and "에센셜 베이직 아이템 B" in r.text
    assert "긍정 / 중립 / 부정 비율" in r.text and "자주 나온 키워드" in r.text


def test_compare_selected_products_and_summary(page, ids):
    r = page.get(f"/compare?a={ids['product_c']}&b={ids['product_b']}")
    a_pos = r.text.index("컴포트 데일리 상품 C</div>")
    b_pos = r.text.index("에센셜 베이직 아이템 B</div>")
    assert a_pos < b_pos                                                 # 고른 순서대로
    assert "평균 평점이" in r.text


def test_compare_same_or_foreign_product(page, other_api, ids):
    r = page.get(f"/compare?a={ids['product_a']}&b={ids['product_a']}")
    assert "서로 다른 두 상품을 골라 주세요" in r.text
    r = other_api.get(f"/compare?a={ids['product_a']}&b={ids['product_b']}")
    assert "상품이 2개 이상 있어야 합니다" in r.text and "프리미엄 시그니처" not in r.text


# ── 대시보드 처리할 일
def test_dashboard_todo(page, ids):
    r = page.get("/dashboard")
    assert "처리할 일" in r.text and "답글이 필요한 위험 리뷰" in r.text
    assert "http://testserver/reviews?sentiment=NEG&amp;period=7" in r.text
    assert "아직 업로드 기록이 없습니다" in r.text
    page.post(f"/api/v1/reviews/{ids['risky_a']}/replies", json={"content": "죄송합니다"})
    r = page.get("/dashboard")
    todo = r.text.split('class="card todo-card"')[1].split('class="dashboard-grid"')[0]
    assert ">2건<" in todo                                               # 위험 리뷰 3 → 2


def test_dashboard_todo_done_state(other_api):
    r = other_api.get("/dashboard")
    assert "✓ 처리할 항목 없음" in r.text


# ── 모바일 메뉴 (모든 사이드바 화면 공통)
@pytest.mark.parametrize("path", ["/dashboard", "/products", "/reviews", "/analysis", "/cschatbot", "/compare",
                                  "/products/uploads", "/settings", "/feedback"])
def test_pages_have_mobile_nav(page, path):
    text = page.get(path).text
    assert 'class="nav-toggle"' in text and "@media (max-width: 768px)" in text
    assert 'name="viewport"' in text
