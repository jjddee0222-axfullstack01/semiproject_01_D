"""HTML 화면 테스트 — 6일차 보완: 통계 차트 · 리뷰 블라인드 · 상품 검색 · 위험 키워드 관리 · 비밀번호 찾기"""
import pytest
from sqlalchemy import select

import models as m

pytestmark = pytest.mark.pages


# ── 통계 차트 (분석 화면 / 상품별 대시보드)
def test_analysis_has_charts_filters_and_csv(page, ids):
    r = page.get("/analysis")
    for el in ("chart-monthly-count", "chart-monthly-rating", "chart-sentiment", "chart-keywords",
               'id="f-product"', 'id="f-period"', "/api/v1/exports/stats.csv", "/api/v1/exports/reviews.csv",
               "echarts", "PP.monthlyCount"):
        assert el in r.text, el
    assert f'<option value="{ids["product_a"]}">[상품명] 프리미엄 시그니처 상품 A</option>' in r.text


def test_chart_apis_return_data_for_page(page, ids):
    """차트가 fetch 하는 API 들이 화면 로그인(세션 쿠키) 그대로 데이터를 돌려줌"""
    assert page.get("/api/v1/stats/monthly-trend").json()[0]["count"] >= 1
    assert page.get("/api/v1/stats/sentiment-ratio").json()["total"] == 11
    assert len(page.get("/api/v1/stats/keywords/top?limit=10").json()) == 10
    r = page.get(f"/api/v1/exports/stats.csv?product_id={ids['product_a']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")


def test_product_dashboard_has_trend_chart(page, ids):
    r = page.get(f"/products/{ids['product_a']}")
    assert 'id="chart-product-monthly"' in r.text and f"product_id: {ids['product_a']}" in r.text


# ── 리뷰 블라인드 / 복구
def test_blind_and_restore_from_product_dashboard(page, session, ids):
    url = f"/products/{ids['product_a']}"
    assert page.get(url).text.count('class="review-item"') == 5
    assert page.get(url).text.count("블라인드 처리</button>") == 5

    r = page.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": "  근거 없는 비방  "})
    assert r.url.path == url and "블라인드 처리했습니다" in r.text
    assert r.text.count('class="review-item"') == 4 and "블라인드된 리뷰 (1)" in r.text
    assert "사유: 근거 없는 비방" in r.text and "위험 리뷰 1건" not in r.text     # 위험 리뷰에서도 제외
    review = session.get(m.Review, ids["risky_a"])
    session.refresh(review)
    assert review.status == m.ReviewStatus.BLINDED and review.blind_reason == "근거 없는 비방"

    r = page.post(f"/reviews/{ids['risky_a']}/restore")
    assert "블라인드를 해제했습니다" in r.text and r.text.count('class="review-item"') == 5
    assert "블라인드된 리뷰 (" not in r.text
    actions = session.scalars(select(m.ReviewBlindLog.action).where(m.ReviewBlindLog.review_id == ids["risky_a"])
                              .order_by(m.ReviewBlindLog.id)).all()
    assert actions == [m.BlindAction.BLIND, m.BlindAction.RESTORE]


@pytest.mark.parametrize("reason, message", [("", "사유를 입력해 주세요"), ("   ", "사유를 입력해 주세요"),
                                             ("가" * 501, "500자 이하")])
def test_blind_requires_reason(page, session, ids, reason, message):
    r = page.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": reason})
    assert message in r.text
    assert session.get(m.Review, ids["risky_a"]).status == m.ReviewStatus.VISIBLE


def test_blind_twice_and_restore_visible(page, ids):
    page.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": "악성"})
    assert "이미 블라인드된 리뷰" in page.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": "악성"}).text
    assert "블라인드 상태인 리뷰가 아닙니다" in page.post(f"/reviews/{ids['positive_a']}/restore").text


def test_blind_other_sellers_review_is_404(other_api, session, ids):
    assert other_api.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": "x"}).status_code == 404
    assert other_api.post(f"/reviews/{ids['risky_a']}/restore").status_code == 404
    assert session.get(m.Review, ids["risky_a"]).status == m.ReviewStatus.VISIBLE


# ── 상품 검색
@pytest.mark.parametrize("q, count, text", [
    ("상품 A", 1, "프리미엄 시그니처 상품 A"),
    ("상품", 3, "상품 C"),
    ("없는상품", 0, "'없는상품'에 해당하는 상품이 없습니다"),
    ("%", 0, "해당하는 상품이 없습니다"),             # LIKE 와일드카드가 그대로 동작하지 않음
])
def test_product_search(page, q, count, text):
    r = page.get("/products", params={"q": q})
    assert r.text.count('" class="product-card">') == count and text in r.text      # 상품 링크 카드 수
    assert f'value="{q}"' in r.text


# ── 위험 키워드 관리 + 재분석
def test_risk_keywords_on_settings(page):
    r = page.get("/settings")
    assert "위험 키워드 관리" in r.text and r.text.count('class="keyword-chip"') == 18


def _analysis(session, review_id):
    session.expire_all()
    return session.scalar(select(m.ReviewAnalysis).where(m.ReviewAnalysis.review_id == review_id))


def _review_words(session, review_id):
    return session.scalars(select(m.Keyword.word).join(m.ReviewKeyword)
                           .where(m.ReviewKeyword.review_id == review_id)).all()


def test_add_delete_risk_keyword_applies_immediately(page, session, ids):
    review_id = ids["positive_a"]          # '배송이 정말 빠르고 … 대만족이에요!' (평점 5, 위험 아님)
    assert _analysis(session, review_id).severity == 0
    risky_before = page.get("/api/v1/stats/summary").json()["risky_count"]

    # 추가하면 그 단어가 들어간 기존 리뷰가 바로 다시 분석됨 (재분석 버튼을 누르지 않아도)
    r = page.post("/settings/risk-keywords", data={"word": "대만족", "weight": "3"})
    assert "추가했습니다" in r.text and "리뷰 1건에 바로 반영" in r.text
    assert r.text.count('class="keyword-chip"') == 19
    analysis = _analysis(session, review_id)
    assert analysis.severity == 3 and analysis.sentiment == m.Polarity.NEG
    assert "대만족" in _review_words(session, review_id)

    assert "이미 등록된" in page.post("/settings/risk-keywords", data={"word": "대만족", "weight": "1"}).text
    assert "입력해 주세요" in page.post("/settings/risk-keywords", data={"word": " ", "weight": "1"}).text
    assert "1~10" in page.post("/settings/risk-keywords", data={"word": "x", "weight": "99"}).text

    # 삭제하면 바로 원래 분석으로 돌아감
    kw_id = session.scalar(select(m.RiskKeyword.id).where(m.RiskKeyword.word == "대만족"))
    r = page.post(f"/settings/risk-keywords/{kw_id}/delete")
    assert "삭제했습니다" in r.text and "리뷰 1건에 바로 반영" in r.text
    assert r.text.count('class="keyword-chip"') == 18
    analysis = _analysis(session, review_id)
    assert analysis.severity == 0 and analysis.sentiment == m.Polarity.POS
    assert "대만족" not in _review_words(session, review_id)
    assert page.get("/api/v1/stats/summary").json()["risky_count"] == risky_before


def test_new_risk_keyword_shows_on_dashboard_and_stats(page, ids):
    def risky_count():
        return page.get("/api/v1/stats/summary").json()["risky_count"]

    before = risky_count()
    page.post("/settings/risk-keywords", data={"word": "대만족", "weight": "2"})
    assert risky_count() == before + 1
    top = {k["word"] for k in page.get("/api/v1/stats/keywords/top", params={"limit": 50}).json()}
    assert "대만족" in top


def test_risk_keyword_without_matching_reviews(page):
    r = page.post("/settings/risk-keywords", data={"word": "유통기한", "weight": "2"})
    assert "앞으로 들어오는 리뷰부터" in r.text


def test_reanalyze_all(page):
    assert "리뷰 11건을" in page.post("/settings/reanalyze").text


def test_cannot_delete_other_sellers_keyword(page, other_api, session):
    kw_id = session.scalar(select(m.RiskKeyword.id).join(m.User).where(m.User.email == "demo@pinpoint.kr"))
    assert "찾을 수 없습니다" in other_api.post(f"/settings/risk-keywords/{kw_id}/delete").text
    assert session.get(m.RiskKeyword, kw_id) is not None


def test_settings_error_still_shows_keywords(page):
    r = page.post("/settings", data={"current_password": "wrong", "mall_name": "x",
                                     "mall_platform": "NAVER", "business_number": "1234567890"})
    assert r.status_code == 401 and r.text.count('class="keyword-chip"') == 18


# ── 로그인 화면의 '비밀번호 찾기' 링크
def test_login_links_to_password_reset(client):
    login = client.get("/login").text
    assert 'href="#"' not in login and 'href="http://testserver/password-reset"' in login
