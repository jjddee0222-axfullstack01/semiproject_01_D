"""API 2·3장: 상품 / 리뷰 조회 / 블라인드"""
from datetime import date, timedelta

import pytest

from tests.conftest import API, error_code

pytestmark = pytest.mark.api


# ── 상품
def test_product_list(api):
    body = api.get(f"{API}/products").json()
    assert body["total"] == 3 and body["page"] == 1 and body["size"] == 20
    a = body["items"][0]
    assert a["name"] == "[상품명] 프리미엄 시그니처 상품 A" and a["review_count"] == 5 and a["avg_rating"] == 3.4
    assert "description_embedding" not in a


@pytest.mark.parametrize("query, total", [("q=베이직", 1), ("category=생활", 1), ("q=없는상품", 0), ("q=50%25", 0)])
def test_product_search(api, query, total):
    assert api.get(f"{API}/products?{query}").json()["total"] == total


def test_product_pagination(api):
    body = api.get(f"{API}/products?page=2&size=2").json()
    assert body["total"] == 3 and len(body["items"]) == 1


@pytest.mark.parametrize("query", ["size=101", "page=0", "unknown=1"])
def test_product_list_bad_query(api, query):
    r = api.get(f"{API}/products?{query}")
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"


def test_product_detail(api, ids):
    d = api.get(f"{API}/products/{ids['product_a']}").json()
    assert (d["review_count"], d["avg_rating"], d["positive_count"], d["negative_count"], d["risky_count"]) == (5, 3.4, 2, 3, 1)


def test_product_not_found_and_forbidden(api, other_api, ids):
    assert error_code(api.get(f"{API}/products/99999")) == "PRODUCT_NOT_FOUND"
    r = other_api.get(f"{API}/products/{ids['product_a']}")
    assert r.status_code == 403 and error_code(r) == "FORBIDDEN"
    assert other_api.get(f"{API}/products").json()["total"] == 0


# ── 리뷰 조회
def test_review_list_and_filters(api, ids):
    base = f"{API}/products/{ids['product_a']}/reviews"
    body = api.get(f"{base}?size=2").json()
    assert body["total"] == 5 and len(body["items"]) == 2
    assert body["items"][0]["reviewed_at"] >= body["items"][1]["reviewed_at"]          # 최신순
    assert api.get(f"{base}?sentiment=NEG").json()["total"] == 3
    assert api.get(f"{base}?rating=5").json()["total"] == 2
    today = date.today()
    assert api.get(f"{base}?from={today - timedelta(days=6)}&to={today}").json()["total"] == 3
    assert api.get(f"{base}?from={today}&to={today - timedelta(days=1)}").status_code == 422


def test_review_detail(api, other_api, ids):
    d = api.get(f"{API}/reviews/{ids['risky_a']}").json()
    assert d["analysis"]["severity"] == 3 and d["analysis"]["issue_type"] == "PRODUCT"
    assert d["content_clean"] and d["replies"] == []
    assert {k["word"] for k in d["keywords"]} >= {"불량", "환불"}               # 분석 시 자동 추출
    assert "content_embedding" not in d
    assert error_code(api.get(f"{API}/reviews/99999")) == "REVIEW_NOT_FOUND"
    assert other_api.get(f"{API}/reviews/{ids['risky_a']}").status_code == 403


# ── 블라인드
def test_blind_requires_reason(api, ids):
    for body in ({}, {"reason": "   "}):
        assert api.post(f"{API}/reviews/{ids['risky_a']}/blind", json=body).status_code == 422


def test_blind_and_restore_flow(api, ids):
    url = f"{API}/reviews/{ids['risky_a']}/blind"
    before = api.get(f"{API}/stats/summary").json()

    r = api.post(url, json={"reason": "근거 없는 악성 비방"})
    assert r.status_code == 200
    assert r.json()["status"] == "BLINDED" and r.json()["blind_reason"] == "근거 없는 악성 비방"
    assert error_code(api.post(url, json={"reason": "again"})) == "REVIEW_ALREADY_BLINDED"

    # 블라인드 리뷰는 기본 목록·통계·상품 집계에서 제외
    after = api.get(f"{API}/stats/summary").json()
    assert after["total_reviews"] == before["total_reviews"] - 1
    assert after["risky_count"] == before["risky_count"] - 1
    reviews = f"{API}/products/{ids['product_a']}/reviews"
    assert api.get(reviews).json()["total"] == 4
    assert api.get(f"{reviews}?status=BLINDED").json()["total"] == 1
    assert api.get(f"{API}/products/{ids['product_a']}").json()["review_count"] == 4

    r = api.delete(url)
    assert r.status_code == 200 and r.json()["status"] == "VISIBLE" and r.json()["blind_reason"] is None
    assert error_code(api.delete(url)) == "REVIEW_NOT_BLINDED"
    assert api.get(f"{API}/stats/summary").json() == before

    logs = api.get(f"{API}/reviews/{ids['risky_a']}/blind-logs").json()
    assert [log["action"] for log in logs] == ["BLIND", "RESTORE"]


def test_blind_forbidden_for_other_seller(other_api, ids):
    r = other_api.post(f"{API}/reviews/{ids['risky_a']}/blind", json={"reason": "x"})
    assert r.status_code == 403


# ── 현재 화면용 리뷰 등록 API (/api/reviews)
def test_legacy_review_create_is_analyzed(api, ids):
    r = api.post("/api/reviews", json={"product_id": ids["product_a"], "content": "벌레가 나왔어요", "rating": 4})
    assert r.status_code == 201
    assert r.json()["severity"] == 3 and r.json()["is_risky"] is True and r.json()["issue_type"] == "PRODUCT"
    assert api.post("/api/reviews", json={"product_id": ids["product_a"], "content": "x", "rating": 9}).status_code == 422
