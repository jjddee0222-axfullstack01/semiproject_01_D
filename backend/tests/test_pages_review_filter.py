"""HTML 화면 테스트 — 상품별 대시보드의 리뷰 필터·정렬·페이지 + 리뷰 상세 모달(API)"""
from datetime import date

import pytest
from sqlalchemy import func, select

import models as m
from database import analyze_and_save, seller_risk_keywords
from tests.conftest import API

pytestmark = pytest.mark.pages


def url(ids, query=""):
    return f"/products/{ids['product_a']}" + (f"?{query}" if query else "")


def items(r) -> int:
    return r.text.count('class="review-item"')


def visible_count(session, product_id, *conditions) -> int:
    stmt = (select(func.count(m.Review.id))
            .outerjoin(m.ReviewAnalysis, m.ReviewAnalysis.review_id == m.Review.id)
            .where(m.Review.product_id == product_id, m.Review.status == m.ReviewStatus.VISIBLE, *conditions))
    return session.scalar(stmt)


# ── 필터 화면 기본
def test_filter_bar_and_detail_buttons(page, session, ids):
    r = page.get(url(ids))
    total = visible_count(session, ids["product_a"])
    assert r.status_code == 200
    for text in ('name="sentiment"', 'name="issue"', 'name="rating"', 'name="sort"', 'name="risk"', 'name="q"',
                 f"전체 리뷰 <b>{total}</b>건", 'id="review-modal"', 'role="dialog"'):
        assert text in r.text, text
    assert items(r) == total and r.text.count('class="btn-detail"') == total
    assert "초기화" not in r.text                                       # 필터가 없을 때는 숨김


# ── 필터별 결과
@pytest.mark.parametrize("sentiment", ["POS", "NEG"])
def test_filter_by_sentiment_keeps_summary_stats(page, session, ids, sentiment):
    expected = visible_count(session, ids["product_a"], m.ReviewAnalysis.sentiment == m.Polarity(sentiment))
    total = visible_count(session, ids["product_a"])
    r = page.get(url(ids, f"sentiment={sentiment}"))
    assert items(r) == expected
    assert f"조건에 맞는 리뷰 <b>{expected}</b>건 / 전체 {total}건" in r.text and "초기화" in r.text
    # 상단 통계·요약은 필터와 무관하게 전체 기준
    assert "위험 리뷰 1건이 감지" in r.text and "3.4 / 5.0" in r.text


def test_filter_by_issue_type(page, session, ids):
    issue = session.scalar(
        select(m.ReviewAnalysis.issue_type).join(m.ReviewAnalysis.review)
        .where(m.Review.product_id == ids["product_a"], m.ReviewAnalysis.issue_type.is_not(None)).limit(1))
    expected = visible_count(session, ids["product_a"], m.ReviewAnalysis.issue_type == issue)
    assert expected > 0
    assert items(page.get(url(ids, f"issue={issue.value}"))) == expected


def test_filter_risky_only(page, ids):
    r = page.get(url(ids, "risk=1"))
    assert items(r) == 1 and "불량품이 왔어요" in r.text


def test_filter_by_rating_and_search(page, session, ids):
    assert items(page.get(url(ids, "rating=5"))) == visible_count(session, ids["product_a"], m.Review.rating == 5)
    r = page.get(url(ids, "q=포장"))
    assert items(r) == visible_count(session, ids["product_a"], m.Review.content_raw.contains("포장")) > 0
    r = page.get(url(ids, "q=%25"))                                     # '%' 는 와일드카드가 아니라 글자로 검색
    assert items(r) == 0 and "조건에 맞는 리뷰가 없습니다" in r.text


def test_sort_by_severity_puts_risky_first(page, ids):
    r = page.get(url(ids, "sort=severity"))
    assert r.text.index("불량품이 왔어요") < r.text.index("배송이 정말 빠르고")
    r = page.get(url(ids, "sort=rating_high"))
    assert r.text.index("배송이 정말 빠르고") < r.text.index("불량품이 왔어요")


def test_invalid_filter_values_are_ignored(page, session, ids):
    r = page.get(url(ids, "sentiment=XXX&issue=bad&rating=9&risk=yes&sort=hack&page=abc"))
    assert r.status_code == 200 and items(r) == visible_count(session, ids["product_a"])


def test_blinded_reviews_are_not_in_filtered_list(page, ids):
    page.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": "악성"})
    r = page.get(url(ids, "risk=1"))
    assert items(r) == 0 and "조건에 맞는 리뷰가 없습니다" in r.text


# ── 페이지 이동 (필터 유지)
def test_pagination_keeps_filters(page, session, ids):
    product = session.get(m.Product, ids["product_a"])
    keywords = seller_risk_keywords(session, product.seller_id)
    for i in range(12):
        review = m.Review(product=product, reviewer_name=f"테스터{i}", rating=2,
                          content_raw=f"페이지 테스트 리뷰 {i}", reviewed_at=date(2026, 9, 1))
        session.add(review)
        analyze_and_save(session, review, keywords)
    session.commit()

    r = page.get(url(ids, "rating=2"))
    assert items(r) == 10 and "1 / 2 페이지" in r.text
    assert "rating=2&amp;page=2" in r.text                              # 다음 페이지 링크에 필터 유지
    r = page.get(url(ids, "rating=2&page=2"))
    assert items(r) == 2 and 'aria-current="page">2<' in r.text
    assert items(page.get(url(ids, "rating=2&page=99"))) == 2          # 범위를 넘으면 마지막 페이지


# ── 리뷰 상세 모달이 쓰는 API
def test_review_detail_api_for_modal(api, ids):
    r = api.get(f"{API}/reviews/{ids['risky_a']}")
    assert r.status_code == 200
    body = r.json()
    assert body["analysis"]["severity"] >= 2 and body["analysis"]["issue_type"]
    assert isinstance(body["keywords"], list) and body["keywords"]
    assert body["replies"] == [] and body["status"] == "VISIBLE"


def test_review_detail_api_other_seller_403(other_api, ids):
    assert other_api.get(f"{API}/reviews/{ids['risky_a']}").status_code == 403


def test_other_sellers_filtered_page_is_404(other_api, ids):
    assert other_api.get(url(ids, "sentiment=NEG")).status_code == 404
