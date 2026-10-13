"""API 6장: 위험 키워드 CRUD"""
import pytest

from tests.conftest import API, error_code

pytestmark = pytest.mark.api
URL = f"{API}/risk-keywords"


def test_list_default_keywords(api):
    rows = api.get(URL).json()
    assert len(rows) == 18
    assert [r["weight"] for r in rows] == sorted((r["weight"] for r in rows), reverse=True)


def test_create_update_delete(api):
    new = api.post(URL, json={"word": "냄새", "weight": 2})
    assert new.status_code == 201
    kid = new.json()["id"]
    assert error_code(api.post(URL, json={"word": "냄새"})) == "RISK_KEYWORD_DUPLICATED"
    assert api.post(URL, json={"word": "x", "weight": 99}).status_code == 422

    assert api.patch(f"{URL}/{kid}", json={"weight": 3}).json()["weight"] == 3
    assert error_code(api.patch(f"{URL}/{kid}", json={"word": "환불"})) == "RISK_KEYWORD_DUPLICATED"
    assert api.patch(f"{URL}/{kid}", json={}).status_code == 422

    assert api.delete(f"{URL}/{kid}").status_code == 204
    assert error_code(api.delete(f"{URL}/{kid}")) == "RISK_KEYWORD_NOT_FOUND"


def test_other_seller_cannot_touch(api, other_api):
    kid = api.post(URL, json={"word": "냄새"}).json()["id"]
    assert other_api.patch(f"{URL}/{kid}", json={"weight": 5}).status_code == 403
    assert other_api.delete(f"{URL}/{kid}").status_code == 403
    assert "냄새" not in [k["word"] for k in other_api.get(URL).json()]


def test_new_keyword_used_for_new_reviews(api, ids):
    api.post(URL, json={"word": "냄새", "weight": 3})
    r = api.post("/api/reviews", json={"product_id": ids["product_a"], "content": "냄새가 심해요", "rating": 4})
    assert r.json()["is_risky"] is True
