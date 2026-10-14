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
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

# backend 폴더 안에서 실행(main:app)하든, 최상위 폴더에서 실행(backend.main:app)하든 동작
try:
    from .analysis import RISK_SEVERITY, shop_report, summarize_reviews
    from .api_v1 import setup_api
    from .auth import (LoginRequired, clear_cookie, end_all_sessions, end_session,
                       get_current_user, login_required, start_session)
    from .database import (add_default_risk_keywords, analyze_and_save, init_db, last_month,
                           seller_risk_keywords, this_month)
    from .db import describe_db, get_session
    from .models import (Feedback, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                         ReviewAnalysis, ReviewReply, ReviewStatus, ShopMonthlyStat, User,
                         UserStatus, visible_reviews)
    from .reply_drafts import generate_reply_draft
    from .schemas import ReviewCreate, ReviewCreateResult
    from .security import hash_password, verify_password
except ImportError:
    from analysis import RISK_SEVERITY, shop_report, summarize_reviews
    from api_v1 import setup_api
    from auth import (LoginRequired, clear_cookie, end_all_sessions, end_session,
                      get_current_user, login_required, start_session)
    from database import (add_default_risk_keywords, analyze_and_save, init_db, last_month,
                          seller_risk_keywords, this_month)
    from db import describe_db, get_session
    from models import (Feedback, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                        ReviewAnalysis, ReviewReply, ReviewStatus, ShopMonthlyStat, User,
                        UserStatus, visible_reviews)
    from reply_drafts import generate_reply_draft
    from schemas import ReviewCreate, ReviewCreateResult
    from security import hash_password, verify_password

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
# 인증: sessions 테이블 + session_id 쿠키 (auth.py, /api/v1 과 공용)
# ──────────────────────────────────────────────
@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, _exc: LoginRequired):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"code": "UNAUTHORIZED", "message": "로그인이 필요합니다."}, status_code=401)
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
# 쇼핑몰 분석  (analysis.html)
# ──────────────────────────────────────────────
def purchase_rate(stat) -> Optional[float]:
    """구매율(%) = 구매자 수 / 방문자 수 × 100. 데이터가 없으면 None"""
    if stat is None or not stat.visitors:
        return None
    return stat.buyers / stat.visitors * 100


@app.get("/analysis", name="analysis", response_class=HTMLResponse)
def analysis_page(request: Request,
                  user: User = Depends(login_required),
                  db: Session = Depends(get_session)):
    """쇼핑몰 전체 분석 — 당월 방문자·구매자 / 전월 대비 구매율 / 평균 평점 / AI 분석 리포트 / 칭찬·불만 리뷰"""
    reviews = db.scalars(
        visible_reviews().join(Review.product)
        .where(Product.seller_id == user.id)
        .options(selectinload(Review.analysis), selectinload(Review.product))
        .order_by(Review.reviewed_at.desc(), Review.id.desc())
    ).all()

    stat = db.get(ShopMonthlyStat, (user.id, this_month()))
    rate_now, rate_prev = purchase_rate(stat), purchase_rate(db.get(ShopMonthlyStat, (user.id, last_month())))
    # 전월 대비 구매율 변화율(%). 전월 데이터가 없으면 None → 화면에 '전월 데이터 없음'
    rate_change = (rate_now / rate_prev - 1) * 100 if rate_now is not None and rate_prev else None

    analyzed = [r for r in reviews if r.analysis]
    praise = sorted((r for r in analyzed if r.analysis.sentiment == Polarity.POS),
                    key=lambda r: (-r.rating, -r.reviewed_at.toordinal()))[:3]
    complaints = sorted((r for r in analyzed if r.analysis.sentiment == Polarity.NEG),
                        key=lambda r: (-r.analysis.severity, -r.reviewed_at.toordinal()))[:3]
    positive_summary, negative_summary = summarize_reviews(reviews)

    unreplied_risky = db.scalar(
        visible_reviews().join(Review.product).join(Review.analysis)
        .where(Product.seller_id == user.id, ReviewAnalysis.severity >= RISK_SEVERITY, ~Review.replies.any())
        .with_only_columns(func.count(Review.id))
    )
    blinded_count = db.scalar(
        select(func.count(Review.id)).join(Review.product)
        .where(Product.seller_id == user.id, Review.status == ReviewStatus.BLINDED)
    )

    return render(request, "analysis.html", active_menu="analysis",
                  stats=stat or {"visitors": 0, "buyers": 0},
                  rate_now=rate_now, rate_change=rate_change,
                  avg_rating=sum(r.rating for r in reviews) / len(reviews) if reviews else None,
                  review_count=len(reviews),
                  report=shop_report(reviews),
                  praise=praise, complaints=complaints,
                  positive_summary=positive_summary, negative_summary=negative_summary,
                  unreplied_risky=unreplied_risky, blinded_count=blinded_count)


# ──────────────────────────────────────────────
# CS챗봇 — 답글이 없는 리뷰 + 추천 답글  (cschatbot.html)
# ──────────────────────────────────────────────
CS_LIST_LIMIT = 30
REPLY_MAX_LENGTH = 2000      # API(ReplyCreate)와 같은 기준


@app.get("/cschatbot", name="cschatbot", response_class=HTMLResponse)
def cschatbot_page(request: Request,
                   user: User = Depends(login_required),
                   db: Session = Depends(get_session)):
    """아직 답글이 없는 리뷰를 위험도 높은 순 → 최신순으로 보여 주고, 리뷰마다 추천 답글 초안을 붙인다"""
    unreplied = (visible_reviews().join(Review.product).join(Review.analysis)
                 .where(Product.seller_id == user.id, ~Review.replies.any()))
    reviews = db.scalars(
        unreplied.options(selectinload(Review.analysis), selectinload(Review.product))
        .order_by(ReviewAnalysis.severity.desc(), Review.reviewed_at.desc(), Review.id.desc())
        .limit(CS_LIST_LIMIT)
    ).all()
    risky_unreplied = db.scalar(
        unreplied.where(ReviewAnalysis.severity >= RISK_SEVERITY).with_only_columns(func.count(Review.id))
    )
    total_unreplied = db.scalar(unreplied.with_only_columns(func.count(Review.id)))

    rows = [{"review": r, "draft": generate_reply_draft(r, user.mall_name)[0]} for r in reviews]
    return render(request, "cschatbot.html", active_menu="cschatbot", rows=rows,
                  risky_unreplied=risky_unreplied, total_unreplied=total_unreplied,
                  list_limit=CS_LIST_LIMIT)


@app.post("/cschatbot/replies", name="cschatbot_reply")
def cschatbot_reply(request: Request,
                    review_id: str = Form(""),
                    content: str = Form(""),
                    user: User = Depends(login_required),
                    db: Session = Depends(get_session)):
    """추천 답글(또는 수정한 답글)을 리뷰에 등록 → 등록된 리뷰는 CS챗봇 목록에서 빠진다"""
    content = content.strip()
    review = db.get(Review, int(review_id)) if review_id.isdigit() else None

    error = None
    if review is None or review.product.seller_id != user.id:
        error = "리뷰를 찾을 수 없습니다."
    elif review.status == ReviewStatus.BLINDED:
        error = "블라인드된 리뷰에는 답글을 등록할 수 없습니다."
    elif not content:
        error = "답글 내용을 입력해 주세요."
    elif len(content) > REPLY_MAX_LENGTH:
        error = f"답글은 {REPLY_MAX_LENGTH:,}자 이하로 입력해 주세요."

    if error:
        flash(request, error, "error")
        return redirect(request, "cschatbot")

    db.add(ReviewReply(review_id=review.id, author_id=user.id, content=content))
    db.commit()
    flash(request, f"{mask_name(review.reviewer_name or '고객')} 고객님 리뷰에 답글을 등록했습니다.")
    return redirect(request, "cschatbot")


# ──────────────────────────────────────────────
# 리뷰 등록 API (데이터 적재/테스트용) — 등록 시 자동 분석
# ──────────────────────────────────────────────
@app.post("/api/reviews", status_code=201, response_model=ReviewCreateResult)
def add_review(body: ReviewCreate,
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
    return ReviewCreateResult(id=review.id, sentiment=analysis.sentiment, severity=analysis.severity,
                              issue_type=analysis.issue_type, is_risky=analysis.severity >= RISK_SEVERITY)


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
    end_all_sessions(db, user)
    db.commit()

    response = redirect(request, "login")
    clear_cookie(response)
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
# REST API v1 (/api/v1/*, 문서: /docs) — api_v1.py  (화면 라우트 뒤에 등록)
# ──────────────────────────────────────────────
setup_api(app)


# ──────────────────────────────────────────────
# 404  (404page.html)
# ──────────────────────────────────────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return render(request, "404page.html", status_code=404)
    # API 오류는 공통 형식 {code, message}
    return JSONResponse({"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)},
                        status_code=exc.status_code)


if __name__ == "__main__":
    import uvicorn
    # app_dir 을 backend 폴더로 지정 → 현재 위치와 상관없이 main 모듈을 찾음
    uvicorn.run("main:app", app_dir=str(BASE_DIR), reload=True, reload_dirs=[str(BASE_DIR)])
