"""API 5장: 통계·대시보드 (모두 VISIBLE 리뷰만 집계)"""
import re

import pytest
from sqlalchemy import select

import models as m
from tests.conftest import API, error_code

pytestmark = pytest.mark.api


def test_monthly_trend(api):
    rows = api.get(f"{API}/stats/monthly-trend").json()
    assert sum(r["count"] for r in rows) == 11
    assert all(re.fullmatch(r"\d{4}-\d{2}", r["month"]) for r in rows)
    assert [r["month"] for r in rows] == sorted(r["month"] for r in rows)


def test_sentiment_ratio(api, ids):
    body = api.get(f"{API}/stats/sentiment-ratio").json()
    assert body["total"] == 11 and [i["sentiment"] for i in body["items"]] == ["POS", "NEG", "NEU"]
    assert abs(sum(i["ratio"] for i in body["items"]) - 1) < 0.001
    assert api.get(f"{API}/stats/sentiment-ratio?product_id={ids['product_b']}").json()["total"] == 3


def test_summary(api):
    assert api.get(f"{API}/stats/summary").json() == {
        "total_reviews": 11, "avg_rating": 3.36, "negative_ratio": 0.5455, "risky_count": 3}


def test_stats_product_filter_ownership(api, other_api, ids):
    assert error_code(api.get(f"{API}/stats/summary?product_id=99999")) == "PRODUCT_NOT_FOUND"
    assert other_api.get(f"{API}/stats/summary?product_id={ids['product_a']}").status_code == 403


def test_risk_reviews_sorting(api):
    by_severity = api.get(f"{API}/stats/risk-reviews").json()
    assert by_severity["total"] == 3
    severities = [x["severity"] for x in by_severity["items"]]
    assert severities == sorted(severities, reverse=True) and min(severities) >= 2
    latest = api.get(f"{API}/stats/risk-reviews?sort=latest").json()["items"]
    assert [x["reviewed_at"] for x in latest] == sorted((x["reviewed_at"] for x in latest), reverse=True)
    assert {"product_name", "content_raw", "issue_type"} <= set(latest[0])


def test_risk_reviews_filter_and_paging(api):
    body = api.get(f"{API}/stats/risk-reviews?issue_type=PRODUCT&size=1").json()
    assert body["size"] == 1 and len(body["items"]) <= 1
    assert all(x["issue_type"] == "PRODUCT" for x in body["items"])
    assert api.get(f"{API}/stats/risk-reviews?sort=random").status_code == 422


def test_issue_types(api):
    body = api.get(f"{API}/stats/issue-types").json()
    assert [i["issue_type"] for i in body["items"]] == ["PRODUCT", "DELIVERY", "PACKAGING", "ETC"]
    assert body["total"] == sum(i["count"] for i in body["items"]) > 0


def test_keywords_top(api, session, ids):
    pos = m.Keyword(word="배송", polarity=m.Polarity.POS)
    neg = m.Keyword(word="불량", polarity=m.Polarity.NEG)
    review_ids = session.scalars(select(m.Review.id).order_by(m.Review.id).limit(3)).all()
    session.add_all([m.ReviewKeyword(review_id=r, keyword=pos, score=0.5) for r in review_ids])
    session.add(m.ReviewKeyword(review_id=ids["risky_a"], keyword=neg, score=0.9))
    session.commit()

    top = api.get(f"{API}/stats/keywords/top").json()
    assert top[0] == {"rank": 1, "keyword_id": pos.id, "word": "배송", "polarity": "POS", "count": 3}
    assert [k["word"] for k in api.get(f"{API}/stats/keywords/top?polarity=NEG").json()] == ["불량"]
    assert api.get(f"{API}/stats/keywords/top?limit=0").status_code == 422

    api.post(f"{API}/reviews/{ids['risky_a']}/blind", json={"reason": "악성"})          # 블라인드 → 집계 제외
    assert api.get(f"{API}/stats/keywords/top?polarity=NEG").json() == []


@pytest.mark.parametrize("query", ["product_ids={a},{b}", "product_ids={a}&product_ids={b}"])
def test_compare(api, ids, query):
    body = api.get(f"{API}/stats/compare?" + query.format(a=ids["product_a"], b=ids["product_b"])).json()
    a, b = body["products"]
    assert (a["product_id"], a["review_count"], b["review_count"]) == (ids["product_a"], 5, 3)
    assert [s["sentiment"] for s in a["sentiment"]] == ["POS", "NEG", "NEU"]


def test_compare_errors(api, other_api, ids):
    assert api.get(f"{API}/stats/compare?product_ids={ids['product_a']},{ids['product_a']}").status_code == 422
    assert error_code(api.get(f"{API}/stats/compare?product_ids={ids['product_a']},99999")) == "PRODUCT_NOT_FOUND"
    assert other_api.get(f"{API}/stats/compare?product_ids={ids['product_a']},{ids['product_b']}").status_code == 403
