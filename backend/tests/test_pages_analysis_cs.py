"""HTML 화면 테스트 — 쇼핑몰 분석(analysis.html) · CS챗봇(cschatbot.html)"""
import pytest
from sqlalchemy import select

import models as m
from analysis import shop_report
from reply_drafts import generate_reply_draft

pytestmark = pytest.mark.pages


# ── 사이드바
def test_sidebar_links_to_new_pages(page):
    r = page.get("/dashboard")
    assert 'href="http://testserver/analysis"' in r.text and 'href="http://testserver/cschatbot"' in r.text


# ── 쇼핑몰 분석
def test_analysis_page(page):
    r = page.get("/analysis")
    assert r.status_code == 200
    # 데모: 당월 12,450명 / 1,280명, 전월 11,800명 / 1,080명
    #   구매율 10.28% vs 9.15% → +12.3%
    for text in ("쇼핑몰 분석", "12,450 명", "1,280 명", "+12.3% ▲", "당월 구매율 10.3%",
                 "3.4 / 5.0", "리뷰 11개 기준", "AI 분석 봇 리포트", "장점", "개선 방안",
                 "주요 칭찬 리뷰", "주요 불만 리뷰", "답글이 필요한 위험 리뷰가"):
        assert text in r.text, text
    assert r.text.count('class="review-quote"') == 6           # 칭찬 3 + 불만 3
    assert 'class="menu-item active"><a href="http://testserver/analysis"' in r.text


def test_analysis_without_last_month_and_reviews(client):
    """신규 셀러: 리뷰·월 통계가 없어도 화면이 깨지지 않음"""
    from tests.conftest import OTHER, api_login
    assert client.post("/api/v1/auth/signup", json=OTHER).status_code == 201
    api_login(client, OTHER["email"], OTHER["password"])
    r = client.get("/analysis")
    assert r.status_code == 200
    for text in ("전월 데이터 없음", "리뷰 없음", "아직 분석된 리뷰가 없습니다", "답글이 필요한 위험 리뷰가 없습니다"):
        assert text in r.text, text


def test_analysis_rate_down(page, session):
    """당월 구매율이 전월보다 낮으면 빨간 ▼"""
    stat = session.scalar(select(m.ShopMonthlyStat).order_by(m.ShopMonthlyStat.month.desc()))
    stat.buyers = 500
    session.commit()
    assert "% ▼" in page.get("/analysis").text


def test_shop_report_rules(session):
    reviews = session.scalars(select(m.Review)).all()
    report = shop_report(reviews)
    assert report["positive_count"] + report["negative_count"] == 11
    assert report["recommendations"] and report["issue_counts"]
    assert shop_report([])["strengths"] == "아직 분석된 리뷰가 없습니다."


# ── CS챗봇
def test_cschatbot_page(page):
    r = page.get("/cschatbot")
    assert r.status_code == 200
    assert "답글을 달아야 할 위험 리뷰가 3건 있습니다" in r.text
    assert r.text.count('class="cs-row"') == 11                # 답글 없는 리뷰 전부
    assert "[긍정 리뷰]" in r.text and "[부정 리뷰]" in r.text
    assert "상품 바로가기" in r.text and 'name="content"' in r.text
    # 위험 리뷰가 맨 위
    first_row = r.text.split('class="cs-row"')[1]
    assert "⚠️" in first_row and "review-box negative" in first_row


def test_reply_drafts_by_sentiment(session, ids):
    pos = session.get(m.Review, ids["positive_a"])
    neg = session.get(m.Review, ids["risky_a"])
    assert "감사합니다" in generate_reply_draft(pos, "몰")[0] and "죄송" not in generate_reply_draft(pos, "몰")[0]
    assert "교환 또는 환불" in generate_reply_draft(neg, "몰")[0]


def test_cschatbot_register_reply(page, session, ids):
    r = page.post("/cschatbot/replies", data={"review_id": ids["risky_a"], "content": "  죄송합니다. 바로 교환해 드릴게요.  "})
    assert r.status_code == 200 and "답글을 등록했습니다" in r.text
    assert "위험 리뷰가 2건" in r.text                          # 3 → 2
    assert r.text.count('class="cs-row"') == 10                # 답글 단 리뷰는 목록에서 빠짐
    reply = session.scalar(select(m.ReviewReply))
    assert reply.review_id == ids["risky_a"] and reply.content == "죄송합니다. 바로 교환해 드릴게요."
    assert reply.author_id is not None
    # API 로도 같은 답글이 보임
    assert page.get(f"/api/v1/reviews/{ids['risky_a']}/replies").json()[0]["content"] == reply.content


@pytest.mark.parametrize("data, message", [
    ({"content": ""}, "답글 내용을 입력해 주세요"),
    ({"content": "가" * 2001}, "2,000자 이하"),
    ({"review_id": "999999", "content": "x"}, "리뷰를 찾을 수 없습니다"),
    ({"review_id": "abc", "content": "x"}, "리뷰를 찾을 수 없습니다"),
])
def test_cschatbot_reply_validation(page, session, ids, data, message):
    r = page.post("/cschatbot/replies", data={"review_id": ids["risky_a"]} | data)
    assert message in r.text
    assert session.scalar(select(m.ReviewReply)) is None


def test_cschatbot_blinded_review(page, session, ids):
    review = session.get(m.Review, ids["risky_a"])
    review.status, review.blind_reason = m.ReviewStatus.BLINDED, "악성"
    session.commit()
    assert "위험 리뷰가 2건" in page.get("/cschatbot").text    # 블라인드 리뷰는 목록에서 제외
    r = page.post("/cschatbot/replies", data={"review_id": ids["risky_a"], "content": "x"})
    assert "블라인드된 리뷰에는 답글을 등록할 수 없습니다" in r.text


def test_cschatbot_other_sellers_review(other_api, session, ids):
    r = other_api.post("/cschatbot/replies", data={"review_id": ids["risky_a"], "content": "x"})
    assert "리뷰를 찾을 수 없습니다" in r.text
    assert session.scalar(select(m.ReviewReply)) is None
    assert "모든 리뷰에 답글을 달았어요" in other_api.get("/cschatbot").text
