"""API 1장: 인증·계정 (/auth/*, /users/me)"""
import pytest

from tests.conftest import API, DEMO_EMAIL, DEMO_PASSWORD, OTHER, api_login, error_code

pytestmark = pytest.mark.api


def test_requires_login(client):
    r = client.get(f"{API}/users/me")
    assert r.status_code == 401 and error_code(r) == "UNAUTHORIZED"


def test_signup_success_normalizes(client):
    r = client.post(f"{API}/auth/signup", json=OTHER | {"email": " Other@Shop.KR "})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "other@shop.kr" and body["business_number"] == "2223344444"
    assert body["status"] == "ACTIVE" and "password_hash" not in body


@pytest.mark.parametrize("change, code", [
    ({"email": DEMO_EMAIL}, "EMAIL_DUPLICATED"),
    ({"business_number": "123-45-67890"}, "BUSINESS_NUMBER_DUPLICATED"),
])
def test_signup_conflicts(client, change, code):
    r = client.post(f"{API}/auth/signup", json=OTHER | change)
    assert r.status_code == 409 and error_code(r) == code


def test_validation_error_format(client):
    r = client.post(f"{API}/auth/signup", json=OTHER | {"email": "bad", "business_number": "1"})
    assert r.status_code == 422 and error_code(r) == "VALIDATION_ERROR"
    body = r.json()
    assert body["message"] == "이메일 형식이 올바르지 않습니다."
    assert {tuple(e["loc"]) for e in body["errors"]} >= {("body", "email"), ("body", "business_number")}


def test_login_sets_httponly_session_cookie(client):
    assert error_code(api_login(client, DEMO_EMAIL, "wrong")) == "INVALID_CREDENTIALS"
    r = api_login(client, "DEMO@pinpoint.kr", DEMO_PASSWORD)
    assert r.status_code == 200 and r.json()["email"] == DEMO_EMAIL
    cookie = r.headers["set-cookie"].lower()
    assert "session_id=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert client.get(f"{API}/users/me").json()["mall_name"] == "피인포인트몰"


def test_update_me(api, other_api):
    assert api.patch(f"{API}/users/me", json={}).status_code == 422
    r = api.patch(f"{API}/users/me", json={"business_number": OTHER["business_number"]})
    assert r.status_code == 409 and error_code(r) == "BUSINESS_NUMBER_DUPLICATED"
    r = api.patch(f"{API}/users/me", json={"mall_name": "핀포인트몰", "mall_platform": "OWN"})
    assert r.status_code == 200 and r.json()["mall_name"] == "핀포인트몰" and r.json()["mall_platform"] == "OWN"


def test_change_password(api):
    r = api.patch(f"{API}/users/me/password", json={"current_password": "wrong", "new_password": "Newpass1!"})
    assert r.status_code == 401 and error_code(r) == "INVALID_PASSWORD"
    assert api.patch(f"{API}/users/me/password",
                     json={"current_password": DEMO_PASSWORD, "new_password": "Newpass1!"}).status_code == 204
    assert api_login(api, DEMO_EMAIL, DEMO_PASSWORD).status_code == 401
    assert api_login(api, DEMO_EMAIL, "Newpass1!").status_code == 200


def test_logout_invalidates_session(api):
    token = api.cookies.get("session_id")
    assert api.post(f"{API}/auth/logout").status_code == 204
    api.cookies.set("session_id", token)                     # 예전 쿠키를 다시 넣어도
    assert api.get(f"{API}/users/me").status_code == 401     # 서버에서 세션이 지워져 접근 불가


def test_withdraw(other_api):
    r = other_api.request("DELETE", f"{API}/users/me", json={"password": "wrong"})
    assert r.status_code == 401
    assert other_api.request("DELETE", f"{API}/users/me", json={"password": OTHER["password"]}).status_code == 204
    assert other_api.get(f"{API}/users/me").status_code == 401
    assert api_login(other_api, OTHER["email"], OTHER["password"]).status_code == 401   # 탈퇴 계정 로그인 불가
    # 하드 삭제라 같은 이메일·사업자번호로 다시 가입 가능
    assert other_api.post(f"{API}/auth/signup", json=OTHER).status_code == 201
    assert api_login(other_api, OTHER["email"], OTHER["password"]).status_code == 200
