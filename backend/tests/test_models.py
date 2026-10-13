"""DB 제약 조건·연쇄 삭제 (ERD + 문서 정책)"""
from datetime import date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

import models as m


def _commit_fails(session):
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_seed_data(session):
    assert session.scalar(select(func.count()).select_from(m.User)) == 1
    assert session.scalar(select(func.count()).select_from(m.Product)) == 3
    assert session.scalar(select(func.count()).select_from(m.Review)) == 11
    assert session.scalar(select(func.count()).select_from(m.ReviewAnalysis)) == 11
    assert session.scalar(select(func.count()).select_from(m.RiskKeyword)) == 18
    # 원문과 정제본이 분리 저장됨
    assert all(r.content_clean for r in session.scalars(select(m.Review)))


def test_rating_must_be_1_to_5(session, ids):
    session.add(m.Review(product_id=ids["product_a"], rating=6, content_raw="x", reviewed_at=date.today()))
    _commit_fails(session)


def test_blinded_review_requires_reason(session, ids):
    review = session.get(m.Review, ids["risky_a"])
    review.status = m.ReviewStatus.BLINDED
    _commit_fails(session)


def test_severity_range(session, ids):
    session.get(m.Review, ids["risky_a"]).analysis.severity = 4
    _commit_fails(session)


@pytest.mark.parametrize("field", ["email", "business_number"])
def test_user_unique_fields(session, field):
    demo = session.scalar(select(m.User))
    values = {"email": "new@x.kr", "business_number": "9999999999"} | {field: getattr(demo, field)}
    session.add(m.User(password_hash="x", name="a", mall_name="a", mall_platform=m.MallPlatform.ETC, **values))
    _commit_fails(session)


def test_risk_keyword_unique_per_seller(session):
    session.add(m.RiskKeyword(seller_id=session.scalar(select(m.User.id)), word="환불"))
    _commit_fails(session)


def test_visible_reviews_excludes_blinded(session, ids):
    review = session.get(m.Review, ids["risky_a"])
    review.status, review.blind_reason = m.ReviewStatus.BLINDED, "악성"
    session.commit()
    visible = session.scalars(m.visible_reviews()).all()
    assert len(visible) == 10 and ids["risky_a"] not in [r.id for r in visible]


def test_reply_tree_cascade_and_author_set_null(session, ids):
    demo = session.scalar(select(m.User))
    cs = m.User(email="cs@x.kr", password_hash="x", name="상담", mall_name="m",
                mall_platform=m.MallPlatform.ETC, business_number="5555555555")
    root = m.ReviewReply(review_id=ids["risky_a"], author=cs, content="죄송합니다")
    session.add_all([cs, root]); session.flush()
    session.add(m.ReviewReply(review_id=ids["risky_a"], author=demo, content="교환", parent=root))
    session.commit()

    session.delete(cs); session.commit()                     # 작성자 삭제 → author_id NULL (익명화)
    session.refresh(root)
    assert root.author_id is None

    session.delete(root); session.commit()                   # 상위 답글 삭제 → 하위 답글도 삭제
    assert session.scalar(select(func.count()).select_from(m.ReviewReply)) == 0


def test_product_delete_cascades(session, ids):
    session.add(m.ReviewBlindLog(review_id=ids["risky_a"], action=m.BlindAction.BLIND, reason="x"))
    session.add(m.ReplySuggestion(review_id=ids["risky_a"], draft="d", llm_model="t"))
    session.commit()
    session.delete(session.get(m.Product, ids["product_a"])); session.commit()
    for table in (m.ReviewBlindLog, m.ReplySuggestion):
        assert session.scalar(select(func.count()).select_from(table)) == 0
    assert session.scalar(select(func.count()).select_from(m.Review)) == 6
    assert session.scalar(select(func.count()).select_from(m.ReviewAnalysis)) == 6


def test_session_token_stored_as_hash(api, session):
    rows = session.scalars(select(m.UserSession)).all()
    assert len(rows) == 1
    assert rows[0].session_token_hash != api.cookies.get("session_id")
    assert len(rows[0].session_token_hash) == 64
    assert rows[0].expires_at > datetime.now()
