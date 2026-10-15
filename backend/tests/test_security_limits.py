"""보안: 인증 코드·로그인·비밀번호 찾기 시도 제한 (서버 메모리 기록 → 쿠키 조작으로 우회 불가)"""
import base64
import json

import pytest

import email_verify
import rate_limit
from tests.conftest import API, DEMO_EMAIL, DEMO_PASSWORD, error_code

pytestmark = pytest.mark.pages

RESET = {"name": "홍길동", "email": DEMO_EMAIL, "business_number": "123-45-67890",
         "new_password": "NewPass9!", "new_password_confirm": "NewPass9!"}
SIGNUP_API = {"email": "api@shop.kr", "password": "Abcd123!", "name": "에이피",
              "mall_name": "API몰", "mall_platform": "OWN", "business_number": "555-66-77777"}


@pytest.fixture
def verification_on(monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "1")


def later(monkeypatch, module, seconds):
    """module.time.time 을 seconds 만큼 미래로"""
    real = module.time.time
    monkeypatch.setattr(module.time, "time", lambda: real() + seconds)


def cookie_payload(client) -> str:
    raw = client.cookies.get("pp_flash")
    if not raw:
        return ""
    data = raw.split(".")[0]
    return base64.b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "ignore")


# ── 이메일 인증 코드
def test_code_not_stored_in_cookie(client, verification_on):
    client.post("/email-code", json={"purpose": "reset", "email": DEMO_EMAIL})
    payload = cookie_payload(client)
    assert "hash" not in payload and "email_codes" not in payload


def test_old_cookie_replay_cannot_reset_tries(client, verification_on):
    """발급 직후 쿠키로 되돌려도 틀린 횟수가 초기화되지 않음 (예전 취약점)"""
    client.post("/email-code", json={"purpose": "reset", "email": DEMO_EMAIL})
    saved = client.cookies.get("pp_flash")
    texts = []
    for _ in range(5):
        if saved:
            client.cookies.set("pp_flash", saved)
        texts.append(client.post("/password-reset", data=RESET | {"email_code": "abcdef"}).text)
    assert "(1/5)" in texts[0] and "(4/5)" in texts[3] and "5번 틀렸습니다" in texts[4]


def test_send_limit_per_email(client, verification_on, monkeypatch):
    clock = {"now": email_verify.time.time()}
    monkeypatch.setattr(email_verify.time, "time", lambda: clock["now"])
    for _ in range(email_verify.SEND_LIMIT_PER_EMAIL):
        assert client.post("/email-code", json={"purpose": "signup", "email": "a@shop.kr"}).status_code == 200
        clock["now"] += 61                                  # 재발송 대기(60초) 지남
    r = client.post("/email-code", json={"purpose": "signup", "email": "a@shop.kr"})
    assert r.status_code == 429 and "너무 많습니다" in r.json()["message"]
    clock["now"] += 60 * 60                                 # 1시간 지나면 다시 가능
    assert client.post("/email-code", json={"purpose": "signup", "email": "a@shop.kr"}).status_code == 200


def test_send_limit_per_ip(client, verification_on):
    for i in range(email_verify.SEND_LIMIT_PER_IP):
        assert client.post("/email-code", json={"purpose": "signup", "email": f"u{i}@shop.kr"}).status_code == 200
    r = client.post("/email-code", json={"purpose": "signup", "email": "last@shop.kr"})
    assert r.status_code == 429 and "너무 많습니다" in r.json()["message"]


def test_api_signup_requires_email_code(client, verification_on):
    r = client.post(f"{API}/auth/signup", json=SIGNUP_API)
    assert r.status_code == 400 and error_code(r) == "EMAIL_CODE_INVALID"
    code = client.post("/email-code", json={"purpose": "signup", "email": "api@shop.kr"}).json()["dev_code"]
    assert client.post(f"{API}/auth/signup", json=SIGNUP_API | {"email_code": code}).status_code == 201


# ── 비밀번호 찾기 잠금
def test_reset_lock_survives_cookie_clear(client):
    for _ in range(5):
        client.post("/password-reset", data=RESET | {"name": "틀린이름"})
    client.cookies.clear()                                      # 예전에는 이것으로 잠금이 풀렸음
    r = client.post("/password-reset", data=RESET)
    assert r.status_code == 429 and "잠겼습니다" in r.text


def test_reset_lock_expires(client, monkeypatch):
    for _ in range(5):
        client.post("/password-reset", data=RESET | {"name": "틀린이름"})
    later(monkeypatch, rate_limit, rate_limit.RESET_LOCK_SECONDS + 1)
    assert "비밀번호가 변경되었습니다" in client.post("/password-reset", data=RESET).text


# ── 로그인 잠금
def wrong_login(client, email=DEMO_EMAIL):
    return client.post("/login", data={"email": email, "password": "Wrong123!"})


def test_login_locks_after_five_failures(client):
    texts = [wrong_login(client).text for _ in range(5)]
    assert "2번 더 틀리면" in texts[2] and "1번 더 틀리면" in texts[3] and "잠시 잠겼습니다" in texts[4]
    r = client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 429 and "잠시 잠겼습니다" in r.text      # 맞는 비밀번호도 잠금 동안은 거부
    client.cookies.clear()
    assert client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).status_code == 429


def test_login_lock_expires_and_success_resets(client, monkeypatch):
    for _ in range(4):
        wrong_login(client)
    assert "대시보드" in client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).text
    client.get("/logout")
    assert "1번 더" not in wrong_login(client).text            # 성공하면 실패 횟수 초기화
    for _ in range(4):
        wrong_login(client)
    later(monkeypatch, rate_limit, rate_limit.LOGIN_LOCK_SECONDS + 1)
    assert "대시보드" in client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).text


def test_login_lock_by_ip_across_emails(client):
    for i in range(rate_limit.LOGIN_IP_MAX_FAILS):
        wrong_login(client, f"guess{i}@shop.kr")
    assert client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).status_code == 429


def test_api_login_shares_lock(client):
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": "Wrong123!"})
    r = client.post(f"{API}/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 429 and error_code(r) == "LOGIN_LOCKED"
    assert client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).status_code == 429


def test_password_change_unlocks_login(client):
    for _ in range(5):
        wrong_login(client)
    client.post("/password-reset", data=RESET)                  # 인증 끈 상태(conftest)라 바로 변경
    assert "대시보드" in client.post("/login", data={"email": DEMO_EMAIL, "password": "NewPass9!"}).text


# ── SECRET_KEY 점검
@pytest.mark.parametrize("value, weak", [("", True), ("change-this-to-a-long-random-string", True),
                                          ("short", True), ("x8Fq2-long-random-value-1234567890", False)])
def test_secret_key_warning(value, weak):
    assert bool(rate_limit.secret_key_warning(value)) is weak
