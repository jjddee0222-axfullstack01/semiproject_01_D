"""v1.1 추가 기능: 위험 리뷰 메일 알림 · 부정 키워드 급증 · 셀러 답글 템플릿"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

import alerts
import insights
import models as m
from tests.conftest import API, error_code

pytestmark = pytest.mark.api

D = lambda n: (date.today() - timedelta(days=n)).isoformat()
RISKY_CSV = ("상품명,작성자,평점,리뷰내용,작성일\n"
             f"알림상품,김하나,1,불량이라 환불 요청합니다,{D(0)}\n"
             f"알림상품,이둘,5,아주 만족합니다,{D(0)}\n")
SAFE_CSV = f"상품명,평점,리뷰내용,작성일\n안전상품,5,좋아요 만족합니다,{D(0)}\n"


def upload(c, text, name="r.csv"):
    return c.post("/products/upload", files={"file": (name, text.encode(), "text/csv")})


# ── 알림 설정 ─────────────────────────────────
def test_notification_settings_api(api, other_api):
    assert api.get(f"{API}/users/me/notifications").json() == {"risk_email": False}
    assert api.put(f"{API}/users/me/notifications", json={"risk_email": True}).json() == {"risk_email": True}
    assert api.get(f"{API}/users/me/notifications").json() == {"risk_email": True}
    assert other_api.get(f"{API}/users/me/notifications").json() == {"risk_email": False}   # 셀러별
    r = api.put(f"{API}/users/me/notifications", json={"risk_email": True, "x": 1})
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"


def test_notification_settings_page(page):
    assert 'id="notifications"' in page.get("/settings").text
    r = page.post("/settings/notifications", data={"risk_email": "1"})
    assert "메일 알림을 켰습니다" in r.text and 'name="risk_email" value="1" checked' in r.text
    r = page.post("/settings/notifications", data={})
    assert "메일 알림을 껐습니다" in r.text


def test_upload_risky_notice_without_mail_when_off(page, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send_mail", lambda *a: sent.append(a))
    r = upload(page, RISKY_CSV)
    assert "위험 리뷰 1건이 있습니다" in r.text and "알림 메일 발송" not in r.text
    assert sent == []


def test_upload_risky_sends_mail_when_on(page, monkeypatch, capsys):
    page.post("/settings/notifications", data={"risk_email": "1"})
    r = upload(page, RISKY_CSV, "risky.csv")
    assert "위험 리뷰 1건이 있습니다" in r.text and "(알림 메일 발송)" in r.text
    out = capsys.readouterr().out                       # MAIL_HOST 없음 → 개발 모드: 콘솔 출력
    assert "알림 메일 → demo@pinpoint.kr" in out and "'risky.csv'" in out
    assert "김*" in out and "김하나" not in out             # 작성자 이름 가림
    assert "아주 만족합니다" not in out                       # 위험 리뷰만


def test_upload_mail_uses_smtp_when_configured(page, monkeypatch):
    sent = []
    monkeypatch.setenv("MAIL_HOST", "smtp.example.test")
    monkeypatch.setattr(alerts, "send_mail", lambda to, subject, body: sent.append((to, subject)))
    page.post("/settings/notifications", data={"risk_email": "1"})
    upload(page, RISKY_CSV)
    assert sent == [("demo@pinpoint.kr", "[PIN POINT REVIEW] 위험 리뷰 1건이 새로 들어왔습니다")]


def test_upload_mail_failure_does_not_break_upload(page, monkeypatch):
    monkeypatch.setenv("MAIL_HOST", "smtp.example.test")
    monkeypatch.setattr(alerts, "send_mail", lambda *a: (_ for _ in ()).throw(OSError("down")))
    page.post("/settings/notifications", data={"risk_email": "1"})
    r = upload(page, RISKY_CSV)
    assert r.status_code == 200 and "리뷰 2건 추가" in r.text


def test_upload_no_risky_no_notice(page):
    r = upload(page, SAFE_CSV)
    assert "리뷰 1건 추가" in r.text and "위험 리뷰" not in r.text.split("리뷰 1건 추가")[1][:200]


def test_duplicate_upload_does_not_realert(page):
    upload(page, RISKY_CSV)
    r = upload(page, RISKY_CSV)                          # 전부 중복 → 새 위험 리뷰 없음
    assert "중복 2건 제외" in r.text and "위험 리뷰 1건이 있습니다" not in r.text


def test_notification_setting_deleted_with_account(api, session):
    api.put(f"{API}/users/me/notifications", json={"risk_email": True})
    assert api.request("DELETE", f"{API}/users/me", json={"password": "Pinpoint1!"}).status_code == 204
    assert session.scalar(select(m.NotificationSetting)) is None


# ── 부정 키워드 급증 ───────────────────────────
SURGE_CSV = ("상품명,작성자,평점,리뷰내용,작성일\n"
             + "".join(f"급증상품,고객{i},1,환불 해주세요 {i},{D(i)}\n" for i in range(3)))


def test_keyword_surge_detected(api, page):
    assert api.get(f"{API}/stats/keyword-surges").json() == []
    upload(page, SURGE_CSV)
    items = api.get(f"{API}/stats/keyword-surges").json()
    # 데모의 '환불' 리뷰 1건은 11일 전(이전 7일) → 최근 3건 / 이전 1건 = ×3
    assert items[0] == {"word": "환불", "current": 3, "previous": 1, "ratio": 3.0}
    text = page.get("/dashboard").text
    assert "급증한 부정 키워드" in text and "‘환불’" in text and "(×3.0)" in text


def test_keyword_surge_rules(session, ids):
    demo = session.scalar(select(m.User))
    today = date.today()
    assert insights.keyword_surges(session, demo.id, today=today) == []
    # 기준일을 옮겨 보면: 데모 '환불'(11일 전) 1건만 최근 7일 → 3건 미만이라 급증 아님
    assert insights.keyword_surges(session, demo.id, today=today - timedelta(days=9)) == []


def test_keyword_surge_ignores_blinded_and_other_sellers(api, page, other_api, session):
    upload(page, SURGE_CSV)
    assert other_api.get(f"{API}/stats/keyword-surges").json() == []
    rid = session.scalar(select(m.Review.id).where(m.Review.content_raw == "환불 해주세요 0"))
    assert api.post(f"{API}/reviews/{rid}/blind", json={"reason": "테스트"}).status_code == 200
    assert api.get(f"{API}/stats/keyword-surges").json() == []          # 2건만 남음 → 기준 미달


def test_keyword_surge_limit_validation(api):
    r = api.get(f"{API}/stats/keyword-surges?limit=0")
    assert r.status_code == 422


# ── 답글 템플릿 ───────────────────────────────
NEG_TEMPLATE = "{고객명}님, {쇼핑몰명}입니다. {상품명} 관련 불편 죄송합니다.\n{기본 답글}\n- 우리몰 CS팀"


def test_reply_template_api_crud(api, other_api):
    assert api.get(f"{API}/reply-templates").json() == []
    r = api.put(f"{API}/reply-templates/NEG", json={"content": NEG_TEMPLATE})
    assert r.status_code == 200 and r.json()["sentiment"] == "NEG" and r.json()["content"] == NEG_TEMPLATE
    r = api.put(f"{API}/reply-templates/NEG", json={"content": "수정본 {기본 답글}"})
    assert r.json()["content"] == "수정본 {기본 답글}"
    assert [t["sentiment"] for t in api.get(f"{API}/reply-templates").json()] == ["NEG"]
    assert other_api.get(f"{API}/reply-templates").json() == []
    assert other_api.delete(f"{API}/reply-templates/NEG").status_code == 404
    assert api.delete(f"{API}/reply-templates/NEG").status_code == 204
    r = api.delete(f"{API}/reply-templates/NEG")
    assert r.status_code == 404 and error_code(r) == "REPLY_TEMPLATE_NOT_FOUND"


@pytest.mark.parametrize("content,code", [
    ("안녕하세요 {이름}님", "INVALID_TEMPLATE"),
    ("가" * 2001, "VALIDATION_ERROR"),
    ("   ", "VALIDATION_ERROR"),
])
def test_reply_template_api_validation(api, content, code):
    r = api.put(f"{API}/reply-templates/NEG", json={"content": content})
    assert r.status_code == 422 and error_code(r) == code


def test_reply_template_bad_sentiment(api):
    assert api.put(f"{API}/reply-templates/BAD", json={"content": "x"}).status_code == 422


def test_reply_suggestion_uses_template(api, ids):
    base = api.post(f"{API}/reviews/{ids['risky_a']}/reply-suggestions").json()
    assert base["llm_model"] == "template-v1"
    api.put(f"{API}/reply-templates/NEG", json={"content": NEG_TEMPLATE})
    r = api.post(f"{API}/reviews/{ids['risky_a']}/reply-suggestions").json()
    assert r["llm_model"] == "seller-template-v1"
    assert r["draft"].startswith("강**님, 피인포인트몰입니다. [상품명] 프리미엄 시그니처 상품 A 관련")
    assert base["draft"] in r["draft"] and r["draft"].endswith("- 우리몰 CS팀")


def test_cschatbot_uses_template_and_settings_page(page):
    page.post("/settings/reply-templates/NEG", data={"content": NEG_TEMPLATE})
    assert "우리몰 CS팀" in page.get("/cschatbot").text
    text = page.get("/settings").text
    assert "내 템플릿 사용 중" in text and "우리몰 CS팀" in text
    r = page.post("/settings/reply-templates/NEG/reset")
    assert "기본 초안으로 되돌렸습니다" in r.text
    assert "우리몰 CS팀" not in page.get("/cschatbot").text


def test_settings_template_validation_and_empty_resets(page):
    r = page.post("/settings/reply-templates/POS", data={"content": "감사해요 {닉네임}"})
    assert "쓸 수 없는 자리 표시자" in r.text
    page.post("/settings/reply-templates/POS", data={"content": "감사합니다 {고객명}님"})
    r = page.post("/settings/reply-templates/POS", data={"content": "  "})
    assert "긍정 리뷰 답글을 기본 초안으로 되돌렸습니다" in r.text
    r = page.post("/settings/reply-templates/XYZ", data={"content": "a"})
    assert "템플릿 종류를 찾을 수 없습니다" in r.text


def test_template_braces_are_literal(session, ids):
    """셀러가 쓴 다른 중괄호·서식 문자는 그대로 (str.format 미사용)"""
    import reply_drafts as rd
    review = session.get(m.Review, ids["positive_a"])
    assert rd.template_problem("{{ }} 괄호") is not None              # 알 수 없는 자리 표시자
    assert rd.apply_template("100% 만족 {고객명}", review, "몰") == "100% 만족 김**"
