"""단위 테스트: 텍스트 클리닝 / 리뷰 분석 규칙 / 요약 / 비밀번호·세션 토큰 (DB·서버 불필요)"""
from types import SimpleNamespace

import pytest

from analysis import (DEFAULT_RISK_KEYWORDS, RISK_SEVERITY, analyze_review, clean_text,
                      summarize_reviews)
from models import IssueType, Polarity
from security import hash_password, hash_session_token, new_session_token, verify_password

pytestmark = pytest.mark.unit
RISK = DEFAULT_RISK_KEYWORDS


# ── 텍스트 클리닝 (US-10)
@pytest.mark.parametrize("raw, expected", [
    ("<b>배송</b> 빨라요", "배송 빨라요"),
    ("좋아요!!!!! ㅋㅋㅋㅋㅋ", "좋아요!! ㅋㅋ"),
    ("재구매 👍👍 의사 있음~~~", "재구매 의사 있음~~"),
    ("링크 https://example.com/a?b=1 참고", "링크 참고"),
    ("특수@#$문자   여러    공백", "특수 문자 여러 공백"),
    ("", ""),
])
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


# ── 분석 규칙: severity 0~3 / 감성 / 이슈 유형
@pytest.mark.parametrize("content, rating, severity, sentiment", [
    ("불량품이 왔어요. 환불 요청합니다.", 1, 3, Polarity.NEG),        # 낮은 평점 + 위험 키워드
    ("벌레가 나왔어요", 5, 3, Polarity.NEG),                          # 가중치 3 키워드
    ("그냥 별로예요", 2, 2, Polarity.NEG),                            # 낮은 평점만
    ("환불했어요", 5, 2, Polarity.NEG),                               # 위험 키워드만 (가중치 2)
    ("색감이 조금 어두워요", 3, 1, Polarity.NEG),                     # 평점 3 = 아쉬움
    ("배송 빠르고 좋아요", 5, 0, Polarity.POS),
    ("파손 없이 잘 왔어요", 5, 0, Polarity.POS),                      # '파손 없이' 는 위험 아님
])
def test_analyze_review_severity_and_sentiment(content, rating, severity, sentiment):
    result = analyze_review(content, rating, RISK)
    assert (result.severity, result.sentiment) == (severity, sentiment)
    assert 0.0 <= result.sentiment_score <= 1.0


@pytest.mark.parametrize("content, issue", [
    ("배송이 너무 늦게 도착했어요", IssueType.DELIVERY),
    ("포장 상자가 찌그러져 왔어요", IssueType.PACKAGING),
    ("마감 처리가 불량이에요", IssueType.PRODUCT),
    ("그냥 마음에 안 들어요", IssueType.ETC),
])
def test_issue_type_for_negative_reviews(content, issue):
    assert analyze_review(content, 2, RISK).issue_type == issue


def test_positive_review_has_no_issue_type():
    assert analyze_review("배송 빠르고 좋아요", 5, RISK).issue_type is None


def test_seller_risk_keywords_are_used():
    """셀러가 등록한 위험 키워드만으로 판단"""
    assert analyze_review("냄새가 나요", 4, [("냄새", 2)]).severity >= RISK_SEVERITY
    assert analyze_review("냄새가 나요", 4, []).severity < RISK_SEVERITY


def test_summarize_reviews():
    def r(content, sentiment):
        return SimpleNamespace(content_raw=content, analysis=SimpleNamespace(sentiment=sentiment))
    positive, negative = summarize_reviews([
        r("배송이 빨라요", Polarity.POS), r("배송 좋고 품질도 좋아요", Polarity.POS),
        r("포장이 찢어졌어요", Polarity.NEG)])
    assert "'배송'" in positive and "긍정 리뷰 2건" in positive
    assert "'포장'" in negative and "부정 리뷰 1건" in negative
    assert summarize_reviews([]) == ("아직 긍정 리뷰가 없습니다.", "아직 부정 리뷰가 없습니다.")


# ── 비밀번호 / 세션 토큰
def test_password_hash_and_verify():
    hashed = hash_password("Pinpoint1!")
    assert hashed != "Pinpoint1!" and hashed.startswith("pbkdf2_sha256$")
    assert verify_password("Pinpoint1!", hashed)
    assert not verify_password("pinpoint1!", hashed)
    assert hash_password("Pinpoint1!") != hashed               # salt 가 매번 다름
    assert not verify_password("x", "broken-hash")


def test_session_token_is_random_and_hashed():
    a, b = new_session_token(), new_session_token()
    assert a != b and len(a) >= 40
    digest = hash_session_token(a)
    assert len(digest) == 64 and digest != a and digest == hash_session_token(a)
