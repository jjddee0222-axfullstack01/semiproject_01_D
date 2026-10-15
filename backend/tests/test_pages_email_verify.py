"""이메일 인증 코드 — 회원가입 · 비밀번호 변경 (개발 모드: 메일 서버 없이 응답에 코드가 내려옴)"""
import pytest
from sqlalchemy import select

import email_verify
import models as m
from tests.conftest import DEMO_EMAIL

pytestmark = pytest.mark.pages

SIGNUP = {"name": "김신규", "email": "new@shop.kr", "password": "Abcd123!", "password_confirm": "Abcd123!",
          "mall_name": "신규몰", "mall_platform": "OWN", "business_number": "333-44-55555"}
RESET = {"name": "홍길동", "email": DEMO_EMAIL, "business_number": "123-45-67890",
         "new_password": "NewPass9!", "new_password_confirm": "NewPass9!"}


@pytest.fixture(autouse=True)
def verification_on(monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "1")


def send(client, purpose, email):
    return client.post("/email-code", json={"purpose": purpose, "email": email})


def test_forms_show_code_field(client):
    for path in ("/signup", "/password-reset"):
        text = client.get(path).text
        assert 'name="email_code"' in text and "인증 코드 받기" in text


def test_signup_requires_code(client, session):
    r = client.post("/signup", data=SIGNUP)
    assert r.status_code == 400 and "인증 코드를 먼저 받아" in r.text

    body = send(client, "signup", "new@shop.kr").json()
    assert body["ok"] and len(body["dev_code"]) == 6
    wrong = "000000" if body["dev_code"] != "000000" else "111111"
    assert "올바르지 않습니다. (1/5)" in client.post("/signup", data=SIGNUP | {"email_code": wrong}).text

    r = client.post("/signup", data=SIGNUP | {"email_code": body["dev_code"]})
    assert "회원가입이 완료" in r.text
    assert session.scalar(select(m.User).where(m.User.email == "new@shop.kr")) is not None


def test_code_is_bound_to_email_and_single_use(client):
    code = send(client, "signup", "new@shop.kr").json()["dev_code"]
    r = client.post("/signup", data=SIGNUP | {"email": "other@shop.kr", "email_code": code})
    assert "인증 코드를 먼저 받아" in r.text                         # 다른 이메일엔 사용 불가
    assert "회원가입이 완료" in client.post("/signup", data=SIGNUP | {"email_code": code}).text
    again = SIGNUP | {"email": "second@shop.kr", "business_number": "444-55-66666", "email_code": code}
    assert "인증 코드를 먼저 받아" in client.post("/signup", data=again).text


def test_signup_code_rejects_registered_email(client):
    r = send(client, "signup", DEMO_EMAIL)
    assert r.status_code == 409 and "이미 가입된 이메일" in r.json()["message"]


def test_resend_cooldown_and_bad_requests(client):
    assert send(client, "signup", "new@shop.kr").status_code == 200
    r = send(client, "signup", "new@shop.kr")
    assert r.status_code == 429 and "초 뒤에 다시" in r.json()["message"]
    assert send(client, "bogus", "a@b.kr").status_code == 400
    assert send(client, "signup", "not-an-email").status_code == 400


def test_five_wrong_codes_discard(client):
    code = send(client, "signup", "new@shop.kr").json()["dev_code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        client.post("/signup", data=SIGNUP | {"email_code": wrong})
    assert "5번 틀렸습니다" in client.post("/signup", data=SIGNUP | {"email_code": wrong}).text
    assert "인증 코드를 먼저 받아" in client.post("/signup", data=SIGNUP | {"email_code": code}).text


def test_code_expires(client, monkeypatch):
    code = send(client, "signup", "new@shop.kr").json()["dev_code"]
    real = email_verify.time.time
    monkeypatch.setattr(email_verify.time, "time", lambda: real() + email_verify.CODE_VALID_SECONDS + 1)
    assert "만료되었습니다" in client.post("/signup", data=SIGNUP | {"email_code": code}).text


def test_password_reset_with_code(client):
    assert "인증 코드를 먼저 받아" in client.post("/password-reset", data=RESET).text
    code = send(client, "reset", DEMO_EMAIL).json()["dev_code"]
    r = client.post("/password-reset", data=RESET | {"email_code": code})
    assert "비밀번호가 변경되었습니다" in r.text


def test_reset_code_for_unknown_email_looks_the_same(client):
    """가입되지 않은 이메일도 같은 안내 (가입 여부 노출 방지) — 메일은 보내지 않으므로 코드도 없음"""
    body = send(client, "reset", "nobody@shop.kr").json()
    assert body["ok"] and "인증 코드를 보냈습니다" in body["message"] and "dev_code" not in body


def test_smtp_mode_sends_mail(client, monkeypatch):
    sent = []
    monkeypatch.setenv("MAIL_HOST", "smtp.example.com")
    monkeypatch.setattr(email_verify, "send_mail", lambda to, subject, body: sent.append((to, subject, body)))
    body = send(client, "signup", "new@shop.kr").json()
    assert body["ok"] and "dev_code" not in body                       # 실제 메일 모드에선 화면에 코드 없음
    assert sent[0][0] == "new@shop.kr" and "회원가입 인증 코드" in sent[0][1]


def test_smtp_failure_reports_error(client, monkeypatch):
    monkeypatch.setenv("MAIL_HOST", "smtp.example.com")

    def boom(*_):
        raise OSError("down")
    monkeypatch.setattr(email_verify, "send_mail", boom)
    r = send(client, "signup", "new@shop.kr")
    assert r.status_code == 429 and "보내지 못했습니다" in r.json()["message"]


# ── 회원 탈퇴 완료 화면 (Figma)
def test_withdrawn_page_after_withdraw(page):
    from tests.conftest import DEMO_PASSWORD
    r = page.post("/withdraw", data={"current_password": DEMO_PASSWORD})
    assert r.url.path == "/withdrawn" and "회원 탈퇴가 완료되었습니다." in r.text and "처음으로 돌아가기" in r.text
    assert page.get("/withdrawn").url.path == "/login"                 # 한 번만 표시
