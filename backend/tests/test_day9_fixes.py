"""9일차 통합 점검 수정 (I-26~I-30): 입력 길이·비밀번호 규칙 통일, 비밀번호 변경 시 다른 기기 로그아웃,
설정 비밀번호 확인, CS챗봇 중복 처리 방지, 로그아웃 POST 전용"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import main
import models as m
from security import verify_password
from tests.conftest import API, DEMO_EMAIL, DEMO_PASSWORD

pytestmark = pytest.mark.pages

SIGNUP = {"name": "김신규", "email": "new@shop.kr", "password": "Abcd123!", "password_confirm": "Abcd123!",
          "mall_name": "신규몰", "mall_platform": "OWN", "business_number": "333-44-55555"}
SETTINGS = {"current_password": DEMO_PASSWORD, "mall_name": "피인포인트몰", "mall_platform": "NAVER",
            "business_number": "123-45-67890"}


def login_client():
    c = TestClient(main.app)
    c.__enter__()
    assert "대시보드" in c.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).text
    return c


# ── I-26 입력 길이 (DB 컬럼 크기)와 비밀번호 규칙 통일
@pytest.mark.parametrize("field, value, label", [
    ("name", "가" * 51, "이름은(는) 50자 이하"),
    ("mall_name", "몰" * 101, "쇼핑몰 이름은(는) 100자 이하"),
    ("email", "a" * 250 + "@shop.kr", "이메일은(는) 255자 이하"),
])
def test_signup_rejects_too_long(client, session, field, value, label):
    r = client.post("/signup", data=SIGNUP | {field: value})
    assert r.status_code == 400 and label in r.text
    assert session.scalar(select(func.count()).select_from(m.User)) == 1          # 데모 계정만


def test_settings_rejects_too_long_mall_name(page, session):
    r = page.post("/settings", data=SETTINGS | {"mall_name": "몰" * 101})
    assert r.status_code == 400 and "100자 이하" in r.text
    session.expire_all()
    assert session.scalar(select(m.User.mall_name).where(m.User.email == DEMO_EMAIL)) == "피인포인트몰"


def test_screen_password_rule_matches_api(client):
    long_pw = "Aa1!" + "a" * 61                                                   # 65자: API 와 같이 거부
    r = client.post("/signup", data=SIGNUP | {"password": long_pw, "password_confirm": long_pw})
    assert r.status_code == 400 and "8~64자" in r.text


# ── I-27 비밀번호를 바꾸면 다른 기기의 로그인 종료 (지금 화면은 유지)
def test_settings_password_change_ends_other_sessions(page):
    other = login_client()
    try:
        r = page.post("/settings", data=SETTINGS | {"new_password": "Newpass1!", "new_password_confirm": "Newpass1!"})
        assert "다른 기기의 로그인은 모두 종료" in r.text
        assert page.get("/dashboard").url.path == "/dashboard"                   # 지금 기기: 유지
        assert other.get("/dashboard").url.path == "/login"                      # 다른 기기: 로그아웃
    finally:
        other.__exit__(None, None, None)


def test_api_password_change_ends_other_sessions(api):
    other = login_client()
    try:
        r = api.patch(f"{API}/users/me/password", json={"current_password": DEMO_PASSWORD, "new_password": "Newpass1!"})
        assert r.status_code == 204
        assert api.get(f"{API}/users/me").status_code == 200
        assert other.get(f"{API}/users/me").status_code == 401
    finally:
        other.__exit__(None, None, None)


# ── I-28 설정 화면 비밀번호 확인
def test_settings_password_confirm_mismatch(page, session):
    r = page.post("/settings", data=SETTINGS | {"new_password": "Newpass1!", "new_password_confirm": "Newpass2!"})
    assert r.status_code == 400 and "일치하지 않습니다" in r.text
    session.expire_all()
    user = session.scalar(select(m.User).where(m.User.email == DEMO_EMAIL))
    assert verify_password(DEMO_PASSWORD, user.password_hash)                   # 비밀번호 그대로
    assert 'name="new_password_confirm"' in page.get("/settings").text


# ── I-29 CS챗봇 '처리 완료' 중복 저장 방지
def test_cschatbot_done_twice_saves_once(page, session, ids):
    data = {"review_id": str(ids["risky_a"]), "content": "불편을 드려 죄송합니다."}
    page.post("/cschatbot/done", data=data)
    r = page.post("/cschatbot/done", data=data)                                  # 두 번 누르기 / 뒤로 가기 후 재제출
    assert "이미 처리 완료된 리뷰입니다" in r.text
    count = session.scalar(select(func.count()).select_from(m.ReviewReply).where(m.ReviewReply.review_id == ids["risky_a"]))
    assert count == 1


# ── I-30 로그아웃은 POST 로만
def test_get_logout_does_not_log_out(page):
    r = page.get("/logout")
    assert r.url.path == "/dashboard"                                            # 로그인 유지
    assert page.get("/dashboard").url.path == "/dashboard"


def test_post_logout_logs_out(page):
    assert "로그아웃되었습니다" in page.post("/logout").text
    assert page.get("/dashboard").url.path == "/login"


def test_sidebar_logout_is_post_form(page):
    text = page.get("/dashboard").text
    assert '<form method="post" action="http://testserver/logout"' in text
    assert 'href="http://testserver/logout"' not in text
