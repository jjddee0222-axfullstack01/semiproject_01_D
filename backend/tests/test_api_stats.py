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


def test_keywords_top(api, ids):
    """리뷰 분석 시 자동 추출된 키워드('배송 만족', '환불' …)로 TOP N 집계"""
    top = api.get(f"{API}/stats/keywords/top").json()
    assert len(top) == 10 and [k["rank"] for k in top] == list(range(1, 11))
    assert top[0]["count"] == 3 and top[0]["word"] in ("배송 만족", "품질 만족")
    assert all(top[i]["count"] >= top[i + 1]["count"] for i in range(9))          # 많이 나온 순

    neg = [k["word"] for k in api.get(f"{API}/stats/keywords/top?polarity=NEG&limit=50").json()]
    assert "불량" in neg and "환불" in neg and "포장 불만" in neg
    pos = api.get(f"{API}/stats/keywords/top?polarity=POS&limit=50").json()
    assert pos and all(k["polarity"] == "POS" for k in pos)
    assert api.get(f"{API}/stats/keywords/top?limit=0").status_code == 422

    api.post(f"{API}/reviews/{ids['risky_a']}/blind", json={"reason": "악성"})          # 블라인드 → 집계 제외
    neg = [k["word"] for k in api.get(f"{API}/stats/keywords/top?polarity=NEG&limit=50").json()]
    assert "불량" not in neg and "환불" not in neg


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
