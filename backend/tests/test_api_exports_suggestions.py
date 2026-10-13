"""API 7장: CSV 내보내기 / 사과 답글 초안"""
import csv

import pytest

from tests.conftest import API, error_code

pytestmark = pytest.mark.api


def _csv(response):
    assert response.status_code == 200
    assert response.content[:3] == b"\xef\xbb\xbf"                     # 엑셀용 BOM
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.reader(response.content.decode("utf-8-sig").splitlines()))


def test_export_stats_csv(api):
    rows = _csv(api.get(f"{API}/exports/stats.csv"))
    assert rows[0] == ["month", "review_count", "avg_rating", "positive", "negative", "neutral", "risky"]
    assert sum(int(r[1]) for r in rows[1:]) == 11 and sum(int(r[6]) for r in rows[1:]) == 3


def test_export_reviews_csv(api, ids):
    rows = _csv(api.get(f"{API}/exports/reviews.csv?product_id={ids['product_b']}"))
    assert rows[0][-2:] == ["content_raw", "content_clean"] and len(rows) == 4
    api.post(f"{API}/reviews/{ids['risky_a']}/blind", json={"reason": "악성"})
    assert len(_csv(api.get(f"{API}/exports/reviews.csv"))) == 1 + 10        # 블라인드 제외


def test_export_requires_login(client):
    assert client.get(f"{API}/exports/stats.csv").status_code == 401


def test_reply_suggestion(api, ids):
    url = f"{API}/reviews/{ids['risky_a']}/reply-suggestions"
    r = api.post(url)
    assert r.status_code == 201
    draft = r.json()["draft"]
    assert "강** 고객님" in draft and "피인포인트몰" in draft and "교환 또는 환불" in draft
    assert r.json()["llm_model"] == "template-v1"
    assert len(api.get(url).json()) == 1


def test_reply_suggestion_rules(api, other_api, ids):
    r = api.post(f"{API}/reviews/{ids['positive_a']}/reply-suggestions")
    assert r.status_code == 409 and error_code(r) == "NOT_NEGATIVE_REVIEW"
    api.post(f"{API}/reviews/{ids['risky_a']}/blind", json={"reason": "악성"})
    assert error_code(api.post(f"{API}/reviews/{ids['risky_a']}/reply-suggestions")) == "REVIEW_BLINDED"
    assert other_api.get(f"{API}/reviews/{ids['risky_a']}/reply-suggestions").status_code == 403
