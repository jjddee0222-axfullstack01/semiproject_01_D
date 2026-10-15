"""
PIN POINT REVIEW - 테스트 공통 설정 (pytest)

실행
    cd backend
    python -m pip install -r requirements-dev.txt
    python -m pytest                 # 전체
    python -m pytest -m api          # API 만     (-m pages: 화면, -m unit: 단위)
    python -m pytest -k blind -v     # 이름에 blind 가 들어간 테스트만, 자세히

DB
  - 기본: 임시 폴더의 SQLite 파일 → 실제 MariaDB 데이터는 건드리지 않음
  - MariaDB 로 테스트하려면 TEST_DATABASE_URL 에 '테스트 전용' DB 를 지정 (이름이 _test 로 끝나야 함)
      $env:TEST_DATABASE_URL = "mariadb+pymysql://pinpoint:비밀번호@127.0.0.1:3306/pinpoint_test?charset=utf8mb4"
    ※ 테스트마다 모든 테이블을 지웠다가 다시 만듭니다. 운영 DB(pinpoint)는 절대 지정하지 마세요.

테스트마다 DB 를 비우고 데모 데이터(demo@pinpoint.kr, 상품 A·B·C, 리뷰 11개)를 다시 넣습니다.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# ── 앱을 import 하기 전에 테스트용 환경 변수 설정 (backend/.env 보다 우선)
_test_url = os.environ.get("TEST_DATABASE_URL")
if _test_url:
    from sqlalchemy.engine import make_url

    if not (make_url(_test_url).database or "").endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL 의 데이터베이스 이름은 _test 로 끝나야 합니다 (운영 DB 보호).")
    os.environ["DATABASE_URL"] = _test_url
else:
    _tmp_dir = tempfile.mkdtemp(prefix="pinpoint_test_")
    os.environ["DATABASE_URL"] = "sqlite:///" + Path(_tmp_dir, "test.db").as_posix()
os.environ["INTERNAL_API_KEY"] = "test-internal-key"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["COOKIE_SECURE"] = "0"
# 이메일 인증 코드: 기존 테스트는 끄고(0), 인증 테스트에서만 monkeypatch 로 켬. 메일 서버는 사용하지 않음(개발 모드)
os.environ["EMAIL_VERIFICATION"] = "0"
os.environ.pop("MAIL_HOST", None)

import security  # noqa: E402

security._ITERATIONS = 1_000      # 비밀번호 해시를 가볍게 → 테스트 속도 향상 (검증 로직은 동일)

import database  # noqa: E402
import email_verify  # noqa: E402
import rate_limit  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402
import models  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

API = "/api/v1"
DEMO_EMAIL, DEMO_PASSWORD = "demo@pinpoint.kr", "Pinpoint1!"
OTHER = {"email": "other@shop.kr", "password": "Other123!", "name": "이다른",
         "mall_name": "다른몰", "mall_platform": "COUPANG", "business_number": "222-33-44444"}
INTERNAL_HEADERS = {"X-Internal-Key": "test-internal-key"}


# ──────────────────────────────────────────────
# DB
# ──────────────────────────────────────────────
@pytest.fixture(autouse=True)
def fresh_db():
    """테스트마다 테이블을 새로 만들고 데모 데이터 입력"""
    models.Base.metadata.drop_all(db.engine)
    database.init_db()
    rate_limit.clear_all()            # 로그인·비밀번호 찾기 잠금 기록 (서버 메모리)
    email_verify.clear_all()          # 발급된 인증 코드·발송 횟수 (서버 메모리)
    yield


@pytest.fixture
def session():
    """DB 를 직접 확인할 때 사용하는 SQLAlchemy 세션"""
    with db.SessionLocal() as s:
        yield s


# ──────────────────────────────────────────────
# 클라이언트
# ──────────────────────────────────────────────
@pytest.fixture
def client():
    """로그인하지 않은 브라우저"""
    with TestClient(main.app) as c:
        yield c


def api_login(c: TestClient, email: str, password: str):
    return c.post(f"{API}/auth/login", json={"email": email, "password": password})


@pytest.fixture
def api(client):
    """데모 셀러로 로그인한 클라이언트 (API·화면 공용 세션 쿠키)"""
    assert api_login(client, DEMO_EMAIL, DEMO_PASSWORD).status_code == 200
    return client


@pytest.fixture
def other_api():
    """다른 셀러(상품 없음)로 로그인한 별도 클라이언트 — 403 확인용"""
    with TestClient(main.app) as c:
        assert c.post(f"{API}/auth/signup", json=OTHER).status_code == 201
        assert api_login(c, OTHER["email"], OTHER["password"]).status_code == 200
        yield c


@pytest.fixture
def page(client):
    """화면(폼 로그인)으로 로그인한 클라이언트"""
    r = client.post("/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert r.status_code == 200 and "대시보드" in r.text
    return client


# ──────────────────────────────────────────────
# 데모 데이터 찾기 (ID 를 직접 적지 않도록)
# ──────────────────────────────────────────────
@pytest.fixture
def ids(session):
    """데모 상품·리뷰 ID 모음
    product_a/b/c : 상품 A(리뷰 5, 평균 3.4, 위험 1) / B(리뷰 3, 위험 1) / C(리뷰 3, 위험 1)
    risky_a       : 상품 A 의 위험 리뷰 ('불량품이 왔어요. 환불 요청합니다.', 평점 1)
    positive_a    : 상품 A 의 긍정 리뷰 ('배송이 정말 빠르고 …', 평점 5)
    """
    products = session.scalars(select(models.Product).order_by(models.Product.id)).all()

    def review(prefix):
        return session.scalar(select(models.Review.id).where(models.Review.content_raw.startswith(prefix)))

    return {"product_a": products[0].id, "product_b": products[1].id, "product_c": products[2].id,
            "risky_a": review("불량품이 왔어요"), "positive_a": review("배송이 정말 빠르고")}


def error_code(response) -> str:
    """API 공통 오류 형식 {code, message} 에서 code 꺼내기"""
    body = response.json()
    assert set(body) >= {"code", "message"}, body
    return body["code"]
