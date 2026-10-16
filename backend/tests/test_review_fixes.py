"""7일차 2차 점검 수정: CSV 수식 주입 · 운영 모드 인증 코드 · 제한 값 설정 · 잘못된 주소 · 3분류 문구"""
import pytest

import email_verify
import rate_limit
from api_v1 import csv_safe
from tests.conftest import API, DEMO_EMAIL, error_code

pytestmark = pytest.mark.pages


# ── CSV 수식 주입 방지 (I-17)
@pytest.mark.parametrize("value, expected", [
    ('=HYPERLINK("http://x","클릭")', '\'=HYPERLINK("http://x","클릭")'),
    ("+1+1", "'+1+1"), ("-cmd", "'-cmd"), ("@SUM(A1)", "'@SUM(A1)"),
    ("배송이 빨라요", "배송이 빨라요"), (-3, -3), (4.5, 4.5), (None, None),
])
def test_csv_safe(value, expected):
    assert csv_safe(value) == expected


def test_review_export_neutralizes_formula(page, ids):
    page.post("/api/reviews", json={"product_id": ids["product_a"], "rating": 5,
                                    "content": '=HYPERLINK("http://evil.example","클릭")'})
    body = page.get(f"{API}/exports/reviews.csv").content.decode("utf-8-sig")
    line = next(line for line in body.splitlines() if "evil.example" in line)
    assert '"\'=HYPERLINK(' in line and ',"=HYPERLINK(' not in line


# ── 운영 모드(COOKIE_SECURE=1)에서는 인증 코드를 화면에 보여 주지 않음 (I-18)
@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "1")
    monkeypatch.setenv("COOKIE_SECURE", "1")


def test_production_without_mail_server_refuses(client, production):
    for purpose, email in (("reset", DEMO_EMAIL), ("reset", "nobody@shop.kr"), ("signup", "new@shop.kr")):
        r = client.post("/email-code", json={"purpose": purpose, "email": email})
        assert r.status_code == 503 and "dev_code" not in r.json() and "메일 서버" in r.json()["message"]
    assert "MAIL_HOST" in email_verify.mail_config_warning()


def test_production_with_mail_server_sends(client, production, monkeypatch):
    sent = []
    monkeypatch.setenv("MAIL_HOST", "smtp.example.com")
    monkeypatch.setattr(email_verify, "send_mail", lambda to, subject, body: sent.append(to))
    body = client.post("/email-code", json={"purpose": "reset", "email": DEMO_EMAIL}).json()
    assert body["ok"] and "dev_code" not in body and sent == [DEMO_EMAIL]
    assert email_verify.mail_config_warning() == ""


def test_local_dev_mode_still_shows_code(client, monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION", "1")             # COOKIE_SECURE=0 (로컬) + MAIL_HOST 없음
    assert "dev_code" in client.post("/email-code", json={"purpose": "signup", "email": "new@shop.kr"}).json()


# ── 제한 값은 .env 로 바꿀 수 있음 (I-19)
@pytest.mark.parametrize("raw, expected", [("100", 100), (" 50 ", 50), ("80   # 발표용", 80),
                                           ("0", 20), ("-5", 20), ("abc", 20), ("", 20)])
def test_env_int(monkeypatch, raw, expected):
    monkeypatch.setenv("PP_TEST_LIMIT", raw)
    assert rate_limit.env_int("PP_TEST_LIMIT", 20) == expected


# ── 잘못된 상품 주소 (I-20)
@pytest.mark.parametrize("path", ["/products/abc", "/products/99999999999999999999"])
def test_bad_product_path_shows_404_page(page, path):
    r = page.get(path)
    assert r.status_code == 404 and "text/html" in r.headers["content-type"]


def test_bad_product_id_in_api(page):
    r = page.get(f"{API}/products/99999999999999999999")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    assert error_code(page.get(f"{API}/products/abc")) == "VALIDATION_ERROR"     # API 오류 형식은 그대로


# ── 3분류 문구 (I-21)
def test_three_way_sentiment_wording(page):
    assert "긍정 / 중립 / 부정 비율" in page.get("/analysis").text
    text = page.get("/reviews").text
    assert "감성 전체" in text and "긍정·부정 전체" not in text
