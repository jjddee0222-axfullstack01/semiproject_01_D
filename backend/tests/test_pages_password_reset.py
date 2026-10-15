"""HTML 화면 테스트 — 비밀번호 변경하기 (Figma: 이름·email·변경할 비밀번호·비밀번호 확인·사업자 등록 번호 한 화면)"""
import pytest
from sqlalchemy import select

import models as m
from security import verify_password
from tests.conftest import DEMO_EMAIL, DEMO_PASSWORD

pytestmark = pytest.mark.pages

NEW_PW = "NewPass9!"
FORM = {"name": "홍길동", "email": DEMO_EMAIL, "business_number": "123-45-67890",
        "new_password": NEW_PW, "new_password_confirm": NEW_PW}


def reset(client, **change):
    return client.post("/password-reset", data=FORM | change)


def test_reset_page_matches_figma_fields(client):
    r = client.get("/password-reset")
    assert r.status_code == 200 and "비밀번호 변경하기" in r.text
    order = ['name="name"', 'name="email"', 'name="new_password"', 'name="new_password_confirm"',
             'name="business_number"']
    positions = [r.text.index(f) for f in order]
    assert positions == sorted(positions)                           # 피그마 순서 그대로
    assert "(영어 대/소문자, 숫자, 특수문자 포함)" in r.text


def test_login_page_links_to_reset(client):
    assert 'href="http://testserver/password-reset"' in client.get("/login").text


def test_reset_success(client, session):
    r = reset(client, email="  DEMO@pinpoint.kr ", business_number="1234567890")   # 대소문자·하이픈 무관
    assert r.url.path == "/login" and "비밀번호가 변경되었습니다" in r.text
    user = session.scalar(select(m.User).where(m.User.email == DEMO_EMAIL))
    session.refresh(user)
    assert verify_password(NEW_PW, user.password_hash)
    assert client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).status_code == 401
    assert "대시보드" in client.post("/login", data={"email": DEMO_EMAIL, "password": NEW_PW}).text


@pytest.mark.parametrize("change", [{"name": "홍길순"}, {"email": "nobody@x.kr"}, {"business_number": "1112223333"},
                                    {"business_number": "12-34"}])
def test_mismatch_does_not_reveal_which_field(client, change):
    r = reset(client, **change)
    assert r.status_code == 400 and "일치하는 계정이 없습니다" in r.text and "(1/5)" in r.text
    assert 'value="' in r.text                                      # 입력값 유지 (비밀번호는 제외)
    assert NEW_PW not in r.text


@pytest.mark.parametrize("change, message", [
    ({"name": ""}, "모든 항목"),
    ({"new_password": "short", "new_password_confirm": "short"}, "대/소문자"),
    ({"new_password_confirm": "Other9!x"}, "일치하지 않습니다"),
    ({"new_password": DEMO_PASSWORD, "new_password_confirm": DEMO_PASSWORD}, "다른 비밀번호"),
])
def test_input_rules(client, change, message):
    r = reset(client, **change)
    assert r.status_code == 400 and message in r.text


def test_lock_after_five_failures(client):
    for _ in range(4):
        reset(client, name="틀림")
    assert "5번 일치하지 않아 10분 동안 잠깁니다" in reset(client, name="틀림").text
    r = reset(client)                                                # 맞는 정보여도 잠김
    assert r.status_code == 429 and "분 뒤에 다시 시도" in r.text


def test_reset_logs_out_other_devices(page, client, session):
    reset(client)
    assert page.get("/dashboard").url.path == "/login"
    assert not session.scalars(select(m.UserSession)).all()
