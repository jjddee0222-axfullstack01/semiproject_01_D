"""v1.2 셀러 도구 API: 개선 조치·효과, 상세페이지 보완, 별점·내용 불일치, 메모, 응답 시간, 리뷰 활용, 신고 자료, 개인정보 가리기"""
import csv
import io
from datetime import date, timedelta

import pytest
from sqlalchemy import select

import models as m
import seller_tools
from privacy import mask_pii
from tests.conftest import API, error_code

pytestmark = pytest.mark.api
D = lambda n: (date.today() - timedelta(days=n)).isoformat()


def add_review(api, product_id, rating, content, days_ago=0):
    r = api.post(f"{API}/reviews", json={"product_id": product_id, "rating": rating, "content": content,
                                         "reviewed_at": D(days_ago)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── 개인정보 가리기 ─────────────────────────────
@pytest.mark.parametrize("text, masked", [
    ("연락 주세요 010-1234-5678", "연락 주세요 010-****-****"),
    ("01098765432 로 전화", "010-****-**** 로 전화"),
    ("매장 02-123-4567", "매장 02-****-****"),
    ("메일 hong.gil@naver.com 로", "메일 h**@naver.com 로"),
    ("2026-10-01 주문, 3개 12,000원", "2026-10-01 주문, 3개 12,000원"),     # 날짜·금액은 그대로
])
def test_mask_pii(text, masked):
    assert mask_pii(text) == masked


def test_api_review_content_is_masked_but_db_keeps_original(api, ids, session):
    rid = add_review(api, ids["product_a"], 1, "불량입니다 010-1111-2222 로 연락주세요")
    assert "010-****-****" in api.get(f"{API}/reviews/{rid}").json()["content_raw"]
    listed = api.get(f"{API}/products/{ids['product_a']}/reviews?size=50").json()["items"]
    assert all("1111-2222" not in r["content_raw"] for r in listed)
    assert "1111-2222" not in api.get(f"{API}/exports/reviews.csv").text
    assert "010-1111-2222" in session.get(m.Review, rid).content_raw          # 원문 보존


# ── 개선 조치 · 효과 ────────────────────────────
def test_product_action_crud_and_effect(api, ids):
    pid = ids["product_b"]
    for i in range(3):                                     # 조치 전: 포장 불만 3건
        add_review(api, pid, 1, f"포장 박스가 찌그러져 왔어요 {i}", days_ago=12 + i)
    for i in range(4):                                     # 조치 후: 만족 4건
        add_review(api, pid, 5, f"이번엔 포장이 꼼꼼하고 좋아요 {i}", days_ago=i)
    r = api.post(f"{API}/products/{pid}/actions",
                 json={"action_date": D(10), "title": "완충재 2겹으로 변경", "issue_type": "PACKAGING"})
    assert r.status_code == 201
    body = r.json()
    eff = body["effect"]
    assert eff["days"] == 11 and eff["target_label"] == "포장" and eff["tone"] == "good"
    assert eff["before"]["target"] >= 3 and eff["after"]["target"] == 0
    assert [a["title"] for a in api.get(f"{API}/products/{pid}/actions").json()] == ["완충재 2겹으로 변경"]
    assert api.delete(f"{API}/products/{pid}/actions/{body['id']}").status_code == 204
    r = api.delete(f"{API}/products/{pid}/actions/{body['id']}")
    assert r.status_code == 404 and error_code(r) == "PRODUCT_ACTION_NOT_FOUND"


def test_action_effect_waits_for_reviews(api, ids):
    r = api.post(f"{API}/products/{ids['product_c']}/actions", json={"action_date": D(0), "title": "상세페이지 수정"})
    assert r.json()["effect"]["tone"] == "wait" and "이릅니다" in r.json()["effect"]["verdict"]
    future = api.post(f"{API}/products/{ids['product_c']}/actions",
                      json={"action_date": (date.today() + timedelta(days=3)).isoformat(), "title": "다음 주 교체"})
    assert future.json()["effect"]["tone"] == "wait" and "예정" in future.json()["effect"]["verdict"]


def test_action_ownership_and_validation(api, other_api, ids):
    pid = ids["product_a"]
    r = other_api.post(f"{API}/products/{pid}/actions", json={"action_date": D(0), "title": "x"})
    assert r.status_code == 403 and error_code(r) == "FORBIDDEN"
    assert other_api.get(f"{API}/products/{pid}/actions").status_code == 403
    assert other_api.get(f"{API}/products/{pid}/detail-tips").status_code == 403
    assert api.post(f"{API}/products/{pid}/actions", json={"action_date": D(0), "title": ""}).status_code == 422
    assert api.post(f"{API}/products/{pid}/actions", json={"action_date": "어제", "title": "a"}).status_code == 422


# ── 상세페이지 보완 · 불일치 ─────────────────────
def test_detail_tips(api, ids):
    pid = ids["product_a"]
    add_review(api, pid, 2, "사이즈가 생각보다 작아요. 사이즈표가 있었으면 좋겠어요")
    add_review(api, pid, 3, "크기가 작네요 010-9999-8888")
    tips = api.get(f"{API}/products/{pid}/detail-tips").json()
    size = next(t for t in tips if t["topic"] == "사이즈")
    assert size["count"] == 2 and "실측 사이즈표" in size["suggestion"]
    assert all("9999" not in ex for t in tips for ex in t["examples"])       # 예시도 가림


def test_mismatch_count(api, ids, other_api):
    before = api.get(f"{API}/stats/mismatch-count").json()["count"]
    add_review(api, ids["product_a"], 5, "예쁘긴 한데 근데 마감이 아쉬워요")
    add_review(api, ids["product_a"], 4, "좋아요 만족합니다")                 # 불일치 아님
    assert api.get(f"{API}/stats/mismatch-count").json()["count"] == before + 1
    assert api.get(f"{API}/stats/mismatch-count?product_id={ids['product_b']}").json()["count"] == 0
    assert other_api.get(f"{API}/stats/mismatch-count?product_id={ids['product_a']}").status_code == 403


# ── 메모 · 처리 상태 ────────────────────────────
def test_review_memo_crud(api, other_api, ids, session):
    rid = ids["risky_a"]
    assert api.get(f"{API}/reviews/{rid}/memo").status_code == 404
    r = api.put(f"{API}/reviews/{rid}/memo", json={"status": "IN_PROGRESS", "memo": "교환 접수함"})
    assert r.status_code == 200 and r.json()["status"] == "IN_PROGRESS" and r.json()["memo"] == "교환 접수함"
    assert api.put(f"{API}/reviews/{rid}/memo", json={"status": "DONE"}).json()["memo"] is None
    assert other_api.get(f"{API}/reviews/{rid}/memo").status_code == 403
    assert other_api.put(f"{API}/reviews/{rid}/memo", json={"status": "DONE"}).status_code == 403
    assert api.put(f"{API}/reviews/{rid}/memo", json={"status": "WRONG"}).status_code == 422
    assert api.put(f"{API}/reviews/{rid}/memo", json={"memo": "가" * 1001}).status_code == 422
    assert api.delete(f"{API}/reviews/{rid}/memo").status_code == 204
    assert session.scalar(select(m.ReviewMemo)) is None


# ── 응답 시간 ─────────────────────────────────
def test_response_time(api, ids, session):
    empty = api.get(f"{API}/stats/response-time").json()
    assert empty["replied"] == 0 and empty["avg_hours"] is None and empty["overdue_days"] == 3
    api.post(f"{API}/reviews/{ids['risky_a']}/replies", json={"content": "죄송합니다"})
    body = api.get(f"{API}/stats/response-time").json()
    assert body["replied"] == 1 and body["within_day_ratio"] == 100.0
    # 위험 리뷰를 4일 전에 들어온 것으로 바꾸면 '오래 방치' 로 셈
    demo = session.scalar(select(m.User))
    now = seller_tools.response_stats(session, demo.id)["overdue_risky"]
    risky = session.scalars(select(m.Review).join(m.Review.analysis)
                            .where(m.ReviewAnalysis.severity >= 2, ~m.Review.replies.any())).all()
    for r in risky:
        r.created_at = r.created_at - timedelta(days=4)
    session.commit()
    assert api.get(f"{API}/stats/response-time").json()["overdue_risky"] == now + len(risky) > 0


# ── 리뷰 활용 ─────────────────────────────────
def test_best_reviews_and_strengths(api, ids, other_api):
    add_review(api, ids["product_c"], 5, "배송이 빠르고 품질도 좋아요. 재구매 의사 있습니다! 문의 a.b@test.com")
    add_review(api, ids["product_c"], 5, "좋긴 한데 근데 조금 아쉬워요 배송은 빨라요")      # 아쉬움 표현 → 제외
    best = api.get(f"{API}/marketing/best-reviews?product_id={ids['product_c']}").json()
    texts = [b["content"] for b in best]
    assert any("재구매 의사" in t for t in texts) and not any("아쉬워요" in t for t in texts)
    assert all("a.b@test.com" not in t for t in texts) and all("*" in b["reviewer"] or b["reviewer"] == "고객" for b in best)
    st = api.get(f"{API}/marketing/strengths").json()
    assert st["keywords"] and st["keywords"][0]["phrase"] and st["sentences"]
    assert other_api.get(f"{API}/marketing/best-reviews?product_id={ids['product_c']}").status_code == 403
    assert other_api.get(f"{API}/marketing/strengths").json()["keywords"] == []
    assert api.get(f"{API}/marketing/best-reviews?limit=0").status_code == 422


def test_strength_sentence_hides_low_rating(session):
    demo = session.scalar(select(m.User))
    st = seller_tools.strengths(session, demo.id)
    assert st["avg_rating"] < 4 and "평균 ★" not in st["sentences"][0]


# ── 신고 자료 ─────────────────────────────────
def test_blinded_reviews_export(api, other_api, ids):
    api.post(f"{API}/reviews/{ids['risky_a']}/blind", json={"reason": "근거 없는 비방"})
    r = api.get(f"{API}/exports/blinded-reviews.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:3] == ["리뷰ID", "상품명", "작성자"] and len(rows) == 2
    assert rows[1][5].startswith("불량품이 왔어요") and rows[1][6] == "근거 없는 비방" and "블라인드" in rows[1][8]
    assert len(list(csv.reader(io.StringIO(other_api.get(f"{API}/exports/blinded-reviews.csv").content.decode("utf-8-sig"))))) == 1
