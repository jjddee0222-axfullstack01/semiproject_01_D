"""
PIN POINT REVIEW - FastAPI 백엔드 (SQLAlchemy 2.0 + ERD 기준)

실행 (아래 중 아무거나):
    cd backend  →  python -m uvicorn main:app --reload        # backend 폴더 안에서
    python -m uvicorn backend.main:app --reload               # 프로젝트 최상위 폴더에서
    python backend/main.py   (또는 VS Code ▶ 실행)            # 어느 폴더에서든

DB: MariaDB — 접속 정보는 backend/.env (처음이라면 .env.example 복사 → 값 입력,
    계정·DB 생성은 setup_mariadb.sql). 테이블은 서버 시작 시 자동 생성

데모 계정: demo@pinpoint.kr / Pinpoint1!
API 문서: http://127.0.0.1:8000/docs
"""
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

# backend 폴더 안에서 실행(main:app)하든, 최상위 폴더에서 실행(backend.main:app)하든 동작
try:
    from .analysis import RISK_SEVERITY, summarize_reviews
    from .database import (add_default_risk_keywords, analyze_and_save, init_db,
                           seller_risk_keywords, this_month)
    from .db import describe_db, get_session
    from .models import (Feedback, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                         ReviewAnalysis, ReviewStatus, ShopMonthlyStat, User, UserSession,
                         UserStatus, visible_reviews)
    from .security import hash_password, hash_session_token, new_session_token, verify_password
except ImportError:
    from analysis import RISK_SEVERITY, summarize_reviews
    from database import (add_default_risk_keywords, analyze_and_save, init_db,
                          seller_risk_keywords, this_month)
    from db import describe_db, get_session
    from models import (Feedback, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                        ReviewAnalysis, ReviewStatus, ShopMonthlyStat, User, UserSession,
                        UserStatus, visible_reviews)
    from security import hash_password, hash_session_token, new_session_token, verify_password

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    print(f"[PIN POINT] DB: {describe_db()}")
    init_db()            # 서버 시작 시 테이블 생성 + (비어 있으면) 데모 데이터
    yield


app = FastAPI(title="PIN POINT REVIEW", lifespan=lifespan)

# 로그인은 sessions 테이블 + session_id 쿠키로 처리하고,
# 이 미들웨어(서명 쿠키 pp_flash)는 화면 안내 메시지 전달에만 사용
app.add_middleware(SessionMiddleware, session_cookie="pp_flash",
                   secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"))

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ── 세션 쿠키 설정 (05_api_spec: session_id, HttpOnly, Secure, SameSite=Lax)
SESSION_COOKIE = "session_id"
SESSION_TTL = timedelta(days=7)
# 개발(http://127.0.0.1)에서는 Secure 쿠키가 전송되지 않을 수 있어 기본값 False, 운영(HTTPS)에서 1로 설정
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

# ── 입력 규칙
PASSWORD_RULE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")
EMAIL_RULE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_RULE_MSG = "비밀번호는 8자 이상이며 영어 대/소문자, 숫자, 특수문자를 모두 포함해야 합니다."


def normalize_business_number(value: str) -> Optional[str]:
    """'123-45-67890' → '1234567890' (ERD: CHAR(10)). 형식이 틀리면 None"""
    digits = re.sub(r"[\s-]", "", value)
    return digits if re.fullmatch(r"\d{10}", digits) else None


def parse_platform(value: str) -> Optional[MallPlatform]:
    try:
        return MallPlatform(value)
    except ValueError:
        return None


# ──────────────────────────────────────────────
# 템플릿 필터
# ──────────────────────────────────────────────
def mask_name(name: str) -> str:
    """'김민수' → '김**'"""
    return name[0] + "*" * (len(name) - 1) if name else ""


def dotdate(value) -> str:
    """date / datetime / 'YYYY-MM-DD' → 'YYYY.MM.DD'"""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y.%m.%d")
    return str(value)[:10].replace("-", ".")


def bizno(value: str) -> str:
    """'1234567890' → '123-45-67890' (화면 표시용)"""
    return f"{value[:3]}-{value[3:5]}-{value[5:]}" if value and len(value) == 10 else value


templates.env.filters.update(mask_name=mask_name, dotdate=dotdate, bizno=bizno)


# ──────────────────────────────────────────────
# 화면 공통: 플래시 메시지 / 렌더링 / 리다이렉트
# ──────────────────────────────────────────────
def flash(request: Request, message: str, category: str = "success") -> None:
    request.session.setdefault("_flashes", []).append([category, message])


def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    flashes = request.session.pop("_flashes", [])
    context.setdefault("form", {})
    context["current_user"] = getattr(request.state, "user", None)
    context["RISK_SEVERITY"] = RISK_SEVERITY
    context["get_flashed_messages"] = lambda with_categories=False: (
        flashes if with_categories else [m for _, m in flashes])
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(request: Request, route_name: str, **path_params) -> RedirectResponse:
    # POST 처리 후에는 303으로 GET 화면에 이동 (새로고침 시 재전송 방지)
    return RedirectResponse(request.url_for(route_name, **path_params), status_code=303)


# ──────────────────────────────────────────────
# 인증: sessions 테이블 + session_id 쿠키
#   요청 → 쿠키 확인 → 세션 조회·만료 확인 → (리소스 404 → 소유권 403) → 처리  (06_architecture 4장)
# ──────────────────────────────────────────────
class LoginRequired(Exception):
    """로그인하지 않은 사용자가 보호된 화면/API에 접근"""


def get_current_user(request: Request, db: Session = Depends(get_session)) -> Optional[User]:
    user = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = db.scalar(
            select(User)
            .join(UserSession, UserSession.user_id == User.id)
            .where(UserSession.session_token_hash == hash_session_token(token),
                   UserSession.expires_at > datetime.now(),
                   User.status == UserStatus.ACTIVE)
        )
    request.state.user = user
    return user


def login_required(user: Optional[User] = Depends(get_current_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def start_session(db: Session, user: User, response: RedirectResponse) -> None:
    """로그인: 세션 행 생성 + 쿠키 발급 (만료된 세션은 이때 정리)"""
    db.execute(delete(UserSession).where(UserSession.expires_at <= datetime.now()))
    token = new_session_token()
    db.add(UserSession(user_id=user.id, session_token_hash=hash_session_token(token),
                       expires_at=datetime.now() + SESSION_TTL))
    db.commit()
    response.set_cookie(SESSION_COOKIE, token, max_age=int(SESSION_TTL.total_seconds()),
                        httponly=True, secure=COOKIE_SECURE, samesite="lax")


def end_session(db: Session, request: Request, response: RedirectResponse) -> None:
    """로그아웃: 서버에서 세션 행 삭제 + 쿠키 만료 → 기존 쿠키로 접근 불가"""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(UserSession).where(UserSession.session_token_hash == hash_session_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=COOKIE_SECURE, samesite="lax")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, _exc: LoginRequired):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
    flash(request, "로그인이 필요합니다.", "error")
    return redirect(request, "login")


# ──────────────────────────────────────────────
# 로그인 / 회원가입 / 로그아웃  (index.html, joinmembership.html)
# ──────────────────────────────────────────────
@app.get("/", name="index")
def index(request: Request, user=Depends(get_current_user)):
    return redirect(request, "dashboard" if user else "login")


@app.get("/login", name="login", response_class=HTMLResponse)
def login_page(request: Request, user=Depends(get_current_user)):
    if user:
        return redirect(request, "dashboard")
    return render(request, "index.html")


@app.post("/login")
def login(request: Request,
          email: str = Form(""),
          password: str = Form(""),
          db: Session = Depends(get_session)):
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if (user is None or user.status != UserStatus.ACTIVE
            or not verify_password(password, user.password_hash)):
        flash(request, "이메일 또는 비밀번호가 올바르지 않습니다.", "error")
        return render(request, "index.html", status_code=401, form={"email": email})

    response = redirect(request, "dashboard")
    start_session(db, user, response)
    return response


@app.get("/signup", name="signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return render(request, "joinmembership.html")


@app.post("/signup")
def signup(request: Request,
           name: str = Form(""),
           email: str = Form(""),
           password: str = Form(""),
           password_confirm: str = Form(""),
           mall_name: str = Form(""),
           mall_platform: str = Form(""),
           business_number: str = Form(""),
           db: Session = Depends(get_session)):
    form = {"name": name.strip(), "email": email.strip().lower(), "mall_name": mall_name.strip(),
            "mall_platform": mall_platform, "business_number": business_number.strip()}
    platform = parse_platform(mall_platform)
    biz = normalize_business_number(form["business_number"])

    error, status = None, 400
    if not all(form.values()) or not password:
        error = "모든 항목을 입력해주세요."
    elif not EMAIL_RULE.match(form["email"]):
        error = "이메일 형식이 올바르지 않습니다."
    elif not PASSWORD_RULE.match(password):
        error = PASSWORD_RULE_MSG
    elif password != password_confirm:
        error = "비밀번호 확인이 일치하지 않습니다."
    elif platform is None:
        error = "쇼핑몰 플랫폼을 선택해주세요."
    elif biz is None:
        error = "사업자 등록 번호는 숫자 10자리로 입력해주세요. (예: 123-45-67890)"
    elif db.scalar(select(User.id).where(User.email == form["email"])):
        error, status = "이미 가입된 이메일입니다.", 409
    elif db.scalar(select(User.id).where(User.business_number == biz)):
        error, status = "이미 등록된 사업자 등록 번호입니다.", 409

    if error:
        flash(request, error, "error")
        return render(request, "joinmembership.html", status_code=status, form=form)

    user = User(name=form["name"], email=form["email"], password_hash=hash_password(password),
                mall_name=form["mall_name"], mall_platform=platform, business_number=biz)
    db.add(user)
    add_default_risk_keywords(db, user)
    db.commit()
    flash(request, "회원가입이 완료되었습니다. 로그인해주세요.")
    return redirect(request, "login")


@app.get("/logout", name="logout")
@app.post("/logout")
def logout(request: Request, db: Session = Depends(get_session)):
    response = redirect(request, "login")
    end_session(db, request, response)
    flash(request, "로그아웃되었습니다.")
    return response


# ──────────────────────────────────────────────
# 대시보드  (dashboard.html)
# ──────────────────────────────────────────────
@app.get("/dashboard", name="dashboard", response_class=HTMLResponse)
def dashboard(request: Request,
              user: User = Depends(login_required),
              db: Session = Depends(get_session)):
    mine = visible_reviews().join(Review.product).where(Product.seller_id == user.id)

    risky_count = db.scalar(
        mine.join(Review.analysis)
        .where(ReviewAnalysis.severity >= RISK_SEVERITY)
        .with_only_columns(func.count(Review.id))
    )
    recent_reviews = db.scalars(
        mine.order_by(Review.reviewed_at.desc(), Review.id.desc()).limit(3)
    ).all()
    stats = db.get(ShopMonthlyStat, (user.id, this_month())) or {"visitors": 0, "buyers": 0}

    return render(request, "dashboard.html", active_menu="dashboard",
                  risky_count=risky_count, recent_reviews=recent_reviews, stats=stats)


# ──────────────────────────────────────────────
# 상품 조회 / 상품별 대시보드  (products.html, productdashboard.html)
# ──────────────────────────────────────────────
@app.get("/products", name="products", response_class=HTMLResponse)
def products(request: Request,
             user: User = Depends(login_required),
             db: Session = Depends(get_session)):
    """상품 목록 — 평균 별점 / 리뷰 수 / 긍정·부정·위험 리뷰 수 (블라인드 리뷰 제외)"""
    positive = func.sum(case((ReviewAnalysis.sentiment == Polarity.POS, 1), else_=0))
    negative = func.sum(case((ReviewAnalysis.sentiment == Polarity.NEG, 1), else_=0))
    risky = func.sum(case((ReviewAnalysis.severity >= RISK_SEVERITY, 1), else_=0))
    rows = db.execute(
        select(Product,
               func.count(Review.id).label("review_count"),
               func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
               func.coalesce(positive, 0).label("positive_count"),
               func.coalesce(negative, 0).label("negative_count"),
               func.coalesce(risky, 0).label("risky_count"))
        # LEFT JOIN 이라 visible_reviews() 대신 조인 조건에 VISIBLE 을 넣음 (리뷰 없는 상품도 표시)
        .outerjoin(Review, (Review.product_id == Product.id) & (Review.status == ReviewStatus.VISIBLE))
        .outerjoin(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
        .where(Product.seller_id == user.id)
        .group_by(Product.id)
        .order_by(Product.id)
    ).all()

    items = [{"id": p.id, "name": p.name, "category": p.category or "",
              "review_count": n, "avg_rating": float(avg), "positive_count": int(pos),
              "negative_count": int(neg), "risky_count": int(rk)}
             for p, n, avg, pos, neg, rk in rows]
    return render(request, "products.html", active_menu="products", products=items)


@app.get("/products/{product_id}", name="product_dashboard", response_class=HTMLResponse)
def product_dashboard(request: Request,
                      product_id: int,
                      user: User = Depends(login_required),
                      db: Session = Depends(get_session)):
    """상품별 대시보드 — 상품 정보 / 위험 리뷰 / 상세 리뷰 / 구매자 수 / 평균 평점 / 긍정·부정 요약"""
    product = db.get(Product, product_id)
    # 화면에서는 남의 상품도 '없는 페이지'로 처리 (상품 존재 여부를 노출하지 않음). API는 403.
    if product is None or product.seller_id != user.id:
        raise HTTPException(status_code=404)

    reviews = db.scalars(
        visible_reviews()
        .where(Review.product_id == product_id)
        .options(selectinload(Review.analysis))
        .order_by(Review.reviewed_at.desc(), Review.id.desc())
    ).all()
    avg_rating = sum(r.rating for r in reviews) / len(reviews) if reviews else 0.0
    risky_count = sum(1 for r in reviews if r.analysis and r.analysis.severity >= RISK_SEVERITY)
    stat = db.get(ProductMonthlyStat, (product_id, this_month()))
    positive_summary, negative_summary = summarize_reviews(reviews)

    return render(request, "productdashboard.html", active_menu="products",
                  product=product, reviews=reviews, risky_count=risky_count,
                  avg_rating=avg_rating, monthly_buyers=stat.buyers if stat else 0,
                  positive_summary=positive_summary, negative_summary=negative_summary)


# ──────────────────────────────────────────────
# 리뷰 등록 API (데이터 적재/테스트용) — 등록 시 자동 분석
# ──────────────────────────────────────────────
class ReviewIn(BaseModel):
    product_id: int
    content: str = Field(min_length=1, max_length=5000)
    rating: int = Field(ge=1, le=5)
    reviewer_name: Optional[str] = Field(default=None, max_length=50)
    reviewed_at: Optional[date] = None


class ReviewOut(BaseModel):
    id: int
    sentiment: str
    severity: int
    issue_type: Optional[str]
    is_risky: bool


@app.post("/api/reviews", status_code=201, response_model=ReviewOut)
def add_review(body: ReviewIn,
               user: User = Depends(login_required),
               db: Session = Depends(get_session)):
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
    if product.seller_id != user.id:
        raise HTTPException(status_code=403, detail="본인 상품에만 접근할 수 있습니다.")

    review = Review(product_id=product.id, reviewer_name=body.reviewer_name, rating=body.rating,
                    content_raw=body.content.strip(), reviewed_at=body.reviewed_at or date.today())
    db.add(review)
    analysis = analyze_and_save(db, review, seller_risk_keywords(db, user.id))
    db.commit()
    return ReviewOut(id=review.id, sentiment=analysis.sentiment.value, severity=analysis.severity,
                     issue_type=analysis.issue_type.value if analysis.issue_type else None,
                     is_risky=analysis.severity >= RISK_SEVERITY)


# ──────────────────────────────────────────────
# 설정 - 회원정보 수정 / 회원 탈퇴  (informationedit.html)
# ──────────────────────────────────────────────
@app.get("/settings", name="settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = Depends(login_required)):
    return render(request, "informationedit.html", active_menu="settings")


@app.post("/settings")
def settings(request: Request,
             current_password: str = Form(""),
             new_password: str = Form(""),
             mall_name: str = Form(""),
             mall_platform: str = Form(""),
             business_number: str = Form(""),
             user: User = Depends(login_required),
             db: Session = Depends(get_session)):
    mall_name = mall_name.strip()
    platform = parse_platform(mall_platform)
    biz = normalize_business_number(business_number)

    error, status = None, 400
    if not verify_password(current_password, user.password_hash):
        error, status = "현재 비밀번호가 올바르지 않습니다.", 401
    elif not mall_name:
        error = "쇼핑몰 이름을 입력해주세요."
    elif platform is None:
        error = "쇼핑몰 플랫폼을 선택해주세요."
    elif biz is None:
        error = "사업자번호는 숫자 10자리로 입력해주세요. (예: 123-45-67890)"
    elif db.scalar(select(User.id).where(User.business_number == biz, User.id != user.id)):
        error, status = "이미 다른 계정에 등록된 사업자번호입니다.", 409
    elif new_password and not PASSWORD_RULE.match(new_password):
        error = "변경할 " + PASSWORD_RULE_MSG

    if error:
        flash(request, error, "error")
        return render(request, "informationedit.html", status_code=status, active_menu="settings")

    user.mall_name, user.mall_platform, user.business_number = mall_name, platform, biz
    if new_password:
        user.password_hash = hash_password(new_password)
    db.commit()
    flash(request, "회원정보가 저장되었습니다.")
    return redirect(request, "settings")


@app.post("/withdraw", name="withdraw")
def withdraw(request: Request,
             current_password: str = Form(""),
             user: User = Depends(login_required),
             db: Session = Depends(get_session)):
    """회원 탈퇴 (US-04, D5): 비밀번호 재확인 → status=WITHDRAWN 소프트 탈퇴 → 모든 세션 삭제"""
    if not verify_password(current_password, user.password_hash):
        flash(request, "비밀번호가 올바르지 않아 탈퇴할 수 없습니다.", "error")
        return render(request, "informationedit.html", status_code=401, active_menu="settings")

    user.status = UserStatus.WITHDRAWN
    user.withdrawn_at = datetime.now()
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    db.commit()

    response = redirect(request, "login")
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=COOKIE_SECURE, samesite="lax")
    flash(request, "회원 탈퇴가 완료되었습니다.")
    return response


# ──────────────────────────────────────────────
# 의견 보내기  (sendfeedback.html)
# ──────────────────────────────────────────────
@app.get("/feedback", name="feedback", response_class=HTMLResponse)
def feedback_page(request: Request, user: User = Depends(login_required)):
    return render(request, "sendfeedback.html", active_menu="feedback")


@app.post("/feedback")
def feedback(request: Request,
             complaint: str = Form(""),
             suggestion: str = Form(""),
             user: User = Depends(login_required),
             db: Session = Depends(get_session)):
    complaint, suggestion = complaint.strip(), suggestion.strip()
    if not complaint or not suggestion:
        flash(request, "불편 사항과 뭐시기 사항을 모두 입력해 주세요.", "error")
        return render(request, "sendfeedback.html", status_code=400, active_menu="feedback",
                      form={"complaint": complaint, "suggestion": suggestion})

    db.add(Feedback(user_id=user.id, complaint=complaint, suggestion=suggestion))
    db.commit()
    flash(request, "소중한 의견 감사합니다. 빠르게 검토하겠습니다.")
    return redirect(request, "feedback")


# ──────────────────────────────────────────────
# 404  (404page.html)
# ──────────────────────────────────────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return render(request, "404page.html", status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


if __name__ == "__main__":
    import uvicorn
    # app_dir 을 backend 폴더로 지정 → 현재 위치와 상관없이 main 모듈을 찾음
    uvicorn.run("main:app", app_dir=str(BASE_DIR), reload=True, reload_dirs=[str(BASE_DIR)])
