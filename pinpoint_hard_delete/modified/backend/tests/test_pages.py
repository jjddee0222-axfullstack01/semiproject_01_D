"""HTML 화면 테스트 (로그인·회원가입·대시보드·상품·설정·의견 보내기·404)"""
import pytest
from sqlalchemy import func, select

import models as m
from tests.conftest import DEMO_EMAIL, DEMO_PASSWORD, OTHER

pytestmark = pytest.mark.pages


# ── 로그인 전
def test_root_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/login")


@pytest.mark.parametrize("path", ["/dashboard", "/products", "/products/1", "/analysis", "/cschatbot",
                                  "/settings", "/feedback"])
def test_protected_pages_redirect_to_login(client, path):
    r = client.get(path)
    assert r.url.path == "/login" and "로그인이 필요합니다" in r.text


def test_login_page_and_wrong_password(client):
    assert 'name="email"' in client.get("/login").text
    r = client.post("/login", data={"email": DEMO_EMAIL, "password": "wrong"})
    assert r.status_code == 401
    assert "이메일 또는 비밀번호가 올바르지 않습니다" in r.text and f'value="{DEMO_EMAIL}"' in r.text


def test_unknown_page_shows_404(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "존재하지 않는 경로" in r.text


# ── 대시보드 / 상품
def test_dashboard(page):
    r = page.get("/dashboard")
    assert r.status_code == 200
    for text in ("피인포인트몰 대시보드", "위험 리뷰 3건", "12,450 명", "1,280 명", "홍길동 (demo@pinpoint.kr)"):
        assert text in r.text
    assert r.text.count('class="review-item"') == 3                # 최근 리뷰 3개


def test_products_page(page, ids):
    r = page.get("/products")
    assert "[상품명] 프리미엄 시그니처 상품 A" in r.text and "★ 3.4 (리뷰 5개)" in r.text
    assert f'/products/{ids["product_a"]}"' in r.text


def test_product_dashboard_page(page, ids):
    r = page.get(f"/products/{ids['product_a']}")
    for text in ("상품별 대시보드", "위험 리뷰 1건이 감지", "340명", "3.4 / 5.0", "김** 고객님",
                 "칭찬이 주를 이룹니다", "개선 요구가 있습니다"):
        assert text in r.text


def test_other_sellers_product_page_is_404(other_api, ids):
    r = other_api.get(f"/products/{ids['product_a']}")
    assert r.status_code == 404


# ── 회원가입
SIGNUP = {"name": "김신규", "email": "new@shop.kr", "password": "Abcd123!", "password_confirm": "Abcd123!",
          "mall_name": "신규몰", "mall_platform": "OWN", "business_number": "333-44-55555"}


@pytest.mark.parametrize("change, status, message", [
    ({"password": "abc", "password_confirm": "abc"}, 400, "대/소문자"),
    ({"password_confirm": "Different1!"}, 400, "일치하지 않습니다"),
    ({"mall_platform": ""}, 400, "모든 항목"),
    ({"business_number": "12-34"}, 400, "숫자 10자리"),
    ({"email": DEMO_EMAIL}, 409, "이미 가입된 이메일"),
    ({"business_number": "1234567890"}, 409, "이미 등록된 사업자"),
])
def test_signup_validation(client, change, status, message):
    r = client.post("/signup", data=SIGNUP | change)
    assert r.status_code == status and message in r.text
    assert 'value="김신규"' in r.text                              # 입력값 유지


def test_signup_then_login(client, session):
    r = client.post("/signup", data=SIGNUP)
    assert "회원가입이 완료" in r.text
    user = session.scalar(select(m.User).where(m.User.email == "new@shop.kr"))
    assert user.business_number == "3334455555" and user.mall_platform == m.MallPlatform.OWN
    assert len(user.risk_keywords) == 18                             # 기본 위험 키워드
    r = client.post("/login", data={"email": "new@shop.kr", "password": "Abcd123!"})
    assert "신규몰 대시보드" in r.text and "등록된 리뷰가 없습니다" in r.text


# ── 설정 / 탈퇴
def test_settings_update(page, session):
    assert 'value="123-45-67890"' in page.get("/settings").text
    r = page.post("/settings", data={"current_password": "wrong", "mall_name": "x",
                                     "mall_platform": "NAVER", "business_number": "1234567890"})
    assert r.status_code == 401 and "현재 비밀번호" in r.text
    r = page.post("/settings", data={"current_password": DEMO_PASSWORD, "mall_name": "새이름몰",
                                     "mall_platform": "COUPANG", "business_number": "123-45-67890",
                                     "new_password": "Newpass1!"})
    assert "저장되었습니다" in r.text and 'value="COUPANG" selected' in r.text
    page.get("/logout")
    assert "새이름몰 대시보드" in page.post("/login", data={"email": DEMO_EMAIL, "password": "Newpass1!"}).text


def test_withdraw(page, session):
    r = page.post("/withdraw", data={"current_password": "wrong"})
    assert r.status_code == 401 and "탈퇴할 수 없습니다" in r.text
    r = page.post("/withdraw", data={"current_password": DEMO_PASSWORD})
    assert "탈퇴가 완료" in r.text
    # 하드 삭제 (D5): 계정과 계정에 딸린 데이터가 모두 지워짐 (외래키 CASCADE)
    for model in (m.User, m.UserSession, m.Product, m.Review, m.ReviewAnalysis, m.ReviewKeyword,
                  m.RiskKeyword, m.ShopMonthlyStat, m.ProductMonthlyStat):
        assert session.scalar(select(func.count()).select_from(model)) == 0, model.__name__
    assert page.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}).status_code == 401


def test_withdraw_then_signup_again_with_same_email(page):
    """탈퇴 후 같은 이메일·사업자번호로 다시 가입 가능 (UNIQUE 는 유지, 행이 지워져서 가능)"""
    page.post("/withdraw", data={"current_password": DEMO_PASSWORD})
    r = page.post("/signup", data={"name": "홍길동", "email": DEMO_EMAIL, "password": "Again123!",
                                   "password_confirm": "Again123!", "mall_name": "다시몰",
                                   "mall_platform": "NAVER", "business_number": "123-45-67890"})
    assert "회원가입이 완료" in r.text
    r = page.post("/login", data={"email": DEMO_EMAIL, "password": "Again123!"})
    assert "다시몰 대시보드" in r.text and "등록된 리뷰가 없습니다" in r.text      # 예전 데이터는 남지 않음


def test_withdraw_keeps_other_sellers_and_anonymizes_feedback(page, other_api, session):
    page.post("/feedback", data={"complaint": "탈퇴 전 의견", "suggestion": "개선 제안"})
    page.post("/withdraw", data={"current_password": DEMO_PASSWORD})
    assert session.scalars(select(m.User.email)).all() == [OTHER["email"]]      # 다른 셀러는 그대로
    feedback = session.scalar(select(m.Feedback))
    assert feedback.complaint == "탈퇴 전 의견" and feedback.user_id is None      # 의견은 익명으로 남음
    assert session.scalar(select(func.count()).select_from(m.Keyword)) > 0      # 공용 키워드 사전은 유지


# ── 의견 보내기 / 로그아웃
def test_feedback(page, session):
    r = page.post("/feedback", data={"complaint": "느려요", "suggestion": ""})
    assert r.status_code == 400 and "모두 입력" in r.text and ">느려요</textarea>" in r.text
    r = page.post("/feedback", data={"complaint": "느려요", "suggestion": "다크모드"})
    assert "감사합니다" in r.text
    assert session.scalar(select(m.Feedback.suggestion)) == "다크모드"


def test_logout_invalidates_old_cookie(page):
    old_token = page.cookies.get("session_id")
    assert "로그아웃되었습니다" in page.get("/logout").text
    page.cookies.set("session_id", old_token)
    r = page.get("/dashboard")
    assert r.url.path == "/login"
