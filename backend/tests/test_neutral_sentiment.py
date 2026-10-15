"""중립(NEU) 분류 (rule-v2): 답글 초안 · 서버 시작 시 예전 분석 자동 갱신 · 화면 표시"""
import pytest
from sqlalchemy import select

import models as m
from models import Polarity

pytestmark = pytest.mark.pages



def test_neutral_reply_draft(session):
    from reply_drafts import generate_reply_draft
    review = session.scalar(select(m.Review).where(m.Review.reviewer_name == "이지은"))   # 3점 리뷰
    assert review.analysis.sentiment == Polarity.NEU
    draft, _ = generate_reply_draft(review, "피인포인트몰")
    assert "솔직한 리뷰" in draft and "죄송" not in draft


def test_outdated_analysis_reanalyzed_on_startup(session):
    """규칙이 바뀐 뒤 서버를 켜면 예전 model_version 결과를 자동으로 다시 분석"""
    import database
    from analysis import MODEL_VERSION
    review = session.scalar(select(m.Review).where(m.Review.reviewer_name == "이지은"))
    review.analysis.model_version, review.analysis.sentiment = "rule-v1", Polarity.NEG
    session.commit()
    database.init_db()
    session.expire_all()
    assert (review.analysis.model_version, review.analysis.sentiment) == (MODEL_VERSION, Polarity.NEU)


def test_neutral_shown_on_screens(page):
    assert "중립 리뷰" in page.get("/cschatbot").text                 # 답글 없는 3점 리뷰
    assert "/ 중립 2 /" in page.get("/products").text                # 상품 A: 3점 리뷰 2건
