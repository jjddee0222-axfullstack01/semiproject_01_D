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
import csv
import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

# backend 폴더 안에서 실행(main:app)하든, 최상위 폴더에서 실행(backend.main:app)하든 동작
try:
    from .analysis import RISK_SEVERITY, shop_report, summarize_reviews
    from .api_v1 import setup_api
    from .auth import (LoginRequired, clear_cookie, delete_account, end_session,
                       get_current_user, login_required, start_session)
    from .database import (add_default_risk_keywords, analyze_and_save, init_db, last_month,
                           seller_risk_keywords, this_month)
    from .db import describe_db, get_session
    from .models import (BlindAction, Feedback, IssueType, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                         ReviewAnalysis, ReviewBlindLog, ReviewReply, ReviewStatus, RiskKeyword, ShopMonthlyStat, User,
                         UserStatus, visible_reviews)
    from .pipeline import IngestError, decode_csv_bytes, ingest_rows, parse_csv_text
    from .reply_drafts import generate_reply_draft
    from .schemas import ReviewCreate, ReviewCreateResult
    from .security import hash_password, verify_password
except ImportError:
    from analysis import RISK_SEVERITY, shop_report, summarize_reviews
    from api_v1 import setup_api
    from auth import (LoginRequired, clear_cookie, delete_account, end_session,
                      get_current_user, login_required, start_session)
    from database import (add_default_risk_keywords, analyze_and_save, init_db, last_month,
                          seller_risk_keywords, this_month)
    from db import describe_db, get_session
    from models import (BlindAction, Feedback, IssueType, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                        ReviewAnalysis, ReviewBlindLog, ReviewReply, ReviewStatus, RiskKeyword, ShopMonthlyStat, User,
                        UserStatus, visible_reviews)
    from pipeline import IngestError, decode_csv_bytes, ingest_rows, parse_csv_text
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


@app.get("/password-help", name="password_help")
def password_help(request: Request):
    """비밀번호 찾기 (MoSCoW: 이번 범위 제외) — 안내만 표시"""
    flash(request, "비밀번호 찾기는 아직 지원하지 않습니다. 서비스 관리자에게 비밀번호 초기화를 요청해 주세요.", "error")
    return redirect(request, "login")


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
             q: str = "",
             user: User = Depends(login_required),
             db: Session = Depends(get_session)):
    """상품 목록 — 평균 별점 / 리뷰 수 / 긍정·부정·위험 리뷰 수 (블라인드 리뷰 제외). ?q= 상품명 검색"""
    q = q.strip()[:100]
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
        .where(Product.seller_id == user.id,
               Product.name.contains(q, autoescape=True) if q else True)
        .group_by(Product.id)
        .order_by(Product.id)
    ).all()

    items = [{"id": p.id, "name": p.name, "category": p.category or "",
              "review_count": n, "avg_rating": float(avg), "positive_count": int(pos),
              "negative_count": int(neg), "risky_count": int(rk)}
             for p, n, avg, pos, neg, rk in rows]
    return render(request, "products.html", active_menu="products", products=items, q=q)


# ── 리뷰 CSV 업로드 (상품 조회 화면) — 내부 파이프라인(pipeline.py)과 같은 규칙으로 적재·분석
UPLOAD_MAX_BYTES = 5 * 1024 * 1024        # 5MB
UPLOAD_MAX_ROWS = 10_000
UPLOAD_TEMPLATE = ("상품명,카테고리,작성자,평점,리뷰내용,작성일\r\n"
                   "프리미엄 텀블러 500ml,주방,김민수,5,보온이 오래가고 디자인도 예뻐요.,2026-10-01\r\n"
                   "프리미엄 텀블러 500ml,주방,이지은,2,뚜껑이 헐거워서 물이 새요. 교환 원합니다.,2026-10-03\r\n")


@app.get("/products/upload-template.csv", name="products_upload_template")
def products_upload_template(user: User = Depends(login_required)):
    """업로드 양식 CSV (엑셀에서 한글이 깨지지 않게 UTF-8 BOM)"""
    return Response(content=UPLOAD_TEMPLATE.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="review_upload_template.csv"'})


@app.post("/products/upload", name="products_upload")
async def products_upload(request: Request,
                          file: Optional[UploadFile] = File(None),
                          user: User = Depends(login_required),
                          db: Session = Depends(get_session)):
    """리뷰 CSV 업로드 → 상품이 없으면 새로 만들고, 리뷰를 적재한 뒤 바로 분석 (중복·오류 행은 건너뜀)"""
    filename = (file.filename or "").strip() if file else ""
    error = None
    if not filename:
        error = "업로드할 CSV 파일을 선택해 주세요."
    elif not filename.lower().endswith(".csv"):
        error = "CSV 파일(.csv)만 업로드할 수 있습니다. 엑셀은 '다른 이름으로 저장 → CSV'로 저장해 주세요."
    else:
        data = await file.read(UPLOAD_MAX_BYTES + 1)
        if len(data) > UPLOAD_MAX_BYTES:
            error = f"파일이 너무 큽니다. {UPLOAD_MAX_BYTES // (1024 * 1024)}MB 이하로 나눠서 올려 주세요."
        else:
            try:
                rows = parse_csv_text(decode_csv_bytes(data))
            except (IngestError, csv.Error) as exc:
                error = f"CSV를 읽을 수 없습니다: {exc}"
            else:
                if not rows:
                    error = "헤더 아래에 리뷰 데이터가 없습니다."
                elif len(rows) > UPLOAD_MAX_ROWS:
                    error = f"한 번에 {UPLOAD_MAX_ROWS:,}행까지 올릴 수 있습니다. (현재 {len(rows):,}행)"

    if error:
        flash(request, error, "error")
        return redirect(request, "products")

    log, problems = ingest_rows(db, batch_name=f"upload:{user.id}:{filename}", rows=rows, seller=user)
    added = log.total_count - log.duplicate_count - log.missing_count
    message = f"'{filename}' 업로드 완료: 리뷰 {added:,}건 추가"
    if log.duplicate_count:
        message += f", 중복 {log.duplicate_count:,}건 제외"
    if log.missing_count:
        shown = ", ".join(problems[:5]) + (f" 외 {len(problems) - 5}건" if len(problems) > 5 else "")
        message += f", 오류 {log.missing_count:,}건 건너뜀 ({shown})"
    flash(request, message + ".", "success" if added else "error")
    return redirect(request, "products")


# ── 상품별 리뷰 필터 (상품별 대시보드의 '상세 리뷰' 목록에만 적용, 상단 통계·요약은 전체 기준)
REVIEW_PAGE_SIZE = 10
REVIEW_QUERY_MAX = 100
SENTIMENT_LABELS = {"POS": "긍정", "NEG": "부정", "NEU": "중립"}
ISSUE_LABELS = {"PRODUCT": "상품", "DELIVERY": "배송", "PACKAGING": "포장", "ETC": "기타"}
SEVERITY_LABELS = {0: "정상", 1: "주의", 2: "위험", 3: "심각"}
REVIEW_SORTS = {
    "latest": ("최신순", lambda: (Review.reviewed_at.desc(), Review.id.desc())),
    "oldest": ("오래된순", lambda: (Review.reviewed_at.asc(), Review.id.asc())),
    "severity": ("위험도 높은순", lambda: (func.coalesce(ReviewAnalysis.severity, -1).desc(),
                                        Review.reviewed_at.desc(), Review.id.desc())),
    "rating_low": ("평점 낮은순", lambda: (Review.rating.asc(), Review.reviewed_at.desc(), Review.id.desc())),
    "rating_high": ("평점 높은순", lambda: (Review.rating.desc(), Review.reviewed_at.desc(), Review.id.desc())),
}


def review_filters(sentiment: str, issue: str, risk: str, rating: str, q: str, sort: str) -> dict:
    """쿼리 문자열 → 허용된 값만 남긴 필터 (잘못된 값은 조용히 무시 = 전체)"""
    filters = {
        "sentiment": sentiment if sentiment in SENTIMENT_LABELS else "",
        "issue": issue if issue in ISSUE_LABELS else "",
        "risk": "1" if risk == "1" else "",
        "rating": rating if rating in {"1", "2", "3", "4", "5"} else "",
        "q": q.strip()[:REVIEW_QUERY_MAX],
        "sort": sort if sort in REVIEW_SORTS else "latest",
    }
    return filters


def filtered_reviews_stmt(product_id: int, filters: dict):
    """공개(VISIBLE) 리뷰 + 분석 결과 LEFT JOIN 에 필터 조건을 붙인 SELECT"""
    stmt = (visible_reviews()
            .outerjoin(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
            .where(Review.product_id == product_id))
    if filters["sentiment"]:
        stmt = stmt.where(ReviewAnalysis.sentiment == Polarity(filters["sentiment"]))
    if filters["issue"]:
        stmt = stmt.where(ReviewAnalysis.issue_type == IssueType(filters["issue"]))
    if filters["risk"]:
        stmt = stmt.where(ReviewAnalysis.severity >= RISK_SEVERITY)
    if filters["rating"]:
        stmt = stmt.where(Review.rating == int(filters["rating"]))
    if filters["q"]:
        stmt = stmt.where(Review.content_raw.contains(filters["q"], autoescape=True))
    return stmt


@app.get("/products/{product_id}", name="product_dashboard", response_class=HTMLResponse)
def product_dashboard(request: Request,
                      product_id: int,
                      sentiment: str = "",
                      issue: str = "",
                      risk: str = "",
                      rating: str = "",
                      q: str = "",
                      sort: str = "latest",
                      page: str = "1",
                      user: User = Depends(login_required),
                      db: Session = Depends(get_session)):
    """상품별 대시보드 — 상품 정보 / 위험 리뷰 / 상세 리뷰(필터·정렬·페이지) / 구매자 수 / 평균 평점 / 긍정·부정 요약"""
    product = db.get(Product, product_id)
    # 화면에서는 남의 상품도 '없는 페이지'로 처리 (상품 존재 여부를 노출하지 않음). API는 403.
    if product is None or product.seller_id != user.id:
        raise HTTPException(status_code=404)

    # 상단 통계·요약: 필터와 무관하게 이 상품의 공개 리뷰 전체 기준
    all_reviews = db.scalars(
        visible_reviews()
        .where(Review.product_id == product_id)
        .options(selectinload(Review.analysis))
    ).all()
    avg_rating = sum(r.rating for r in all_reviews) / len(all_reviews) if all_reviews else 0.0
    risky_count = sum(1 for r in all_reviews if r.analysis and r.analysis.severity >= RISK_SEVERITY)
    stat = db.get(ProductMonthlyStat, (product_id, this_month()))
    positive_summary, negative_summary = summarize_reviews(all_reviews)

    # 상세 리뷰 목록: 필터 → 개수 → 정렬 → 페이지
    filters = review_filters(sentiment, issue, risk, rating, q, sort)
    stmt = filtered_reviews_stmt(product_id, filters)
    filtered_total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    pages = max(1, -(-filtered_total // REVIEW_PAGE_SIZE))
    page = min(max(int(page) if page.isdigit() else 1, 1), pages)     # 잘못된 page 값은 1페이지
    reviews = db.scalars(
        stmt.options(selectinload(Review.analysis))
        .order_by(*REVIEW_SORTS[filters["sort"]][1]())
        .limit(REVIEW_PAGE_SIZE).offset((page - 1) * REVIEW_PAGE_SIZE)
    ).all()
    # 페이지 링크·초기화에 쓰는 '기본값이 아닌 필터'만 남긴 쿼리
    active_filters = {k: v for k, v in filters.items() if v and not (k == "sort" and v == "latest")}

    blinded_reviews = db.scalars(
        select(Review).where(Review.product_id == product_id, Review.status == ReviewStatus.BLINDED)
        .order_by(Review.blinded_at.desc(), Review.id.desc())
    ).all()

    return render(request, "productdashboard.html", active_menu="products",
                  product=product, reviews=reviews, risky_count=risky_count, blinded_reviews=blinded_reviews,
                  avg_rating=avg_rating, monthly_buyers=stat.buyers if stat else 0,
                  positive_summary=positive_summary, negative_summary=negative_summary,
                  filters=filters, active_filters=active_filters, total_reviews=len(all_reviews),
                  filtered_total=filtered_total, page=page, pages=pages,
                  sentiment_labels=SENTIMENT_LABELS, issue_labels=ISSUE_LABELS,
                  severity_labels=SEVERITY_LABELS,
                  sort_labels={k: label for k, (label, _) in REVIEW_SORTS.items()})


# ──────────────────────────────────────────────
# 리뷰 블라인드 / 복구  (productdashboard.html, US-06 · D2)
#   API(/api/v1/reviews/{id}/blind)와 같은 규칙: 사유 필수, 소프트 삭제, 이력(review_blind_logs) 기록
# ──────────────────────────────────────────────
BLIND_REASON_MAX = 500


def _owned_review_or_404(db: Session, user: User, review_id: int) -> Review:
    review = db.get(Review, review_id)
    # 화면에서는 남의 리뷰도 '없는 페이지'로 처리 (API는 403)
    if review is None or review.product.seller_id != user.id:
        raise HTTPException(status_code=404)
    return review


@app.post("/reviews/{review_id}/blind", name="review_blind")
def review_blind(request: Request,
                 review_id: int,
                 reason: str = Form(""),
                 user: User = Depends(login_required),
                 db: Session = Depends(get_session)):
    review = _owned_review_or_404(db, user, review_id)
    reason = reason.strip()
    if review.status == ReviewStatus.BLINDED:
        flash(request, "이미 블라인드된 리뷰입니다.", "error")
    elif not reason:
        flash(request, "블라인드 사유를 입력해 주세요.", "error")
    elif len(reason) > BLIND_REASON_MAX:
        flash(request, f"블라인드 사유는 {BLIND_REASON_MAX}자 이하로 입력해 주세요.", "error")
    else:
        review.status, review.blind_reason = ReviewStatus.BLINDED, reason
        review.blinded_by, review.blinded_at = user.id, datetime.now()
        db.add(ReviewBlindLog(review=review, actor_id=user.id, action=BlindAction.BLIND, reason=reason))
        db.commit()
        flash(request, "리뷰를 블라인드 처리했습니다. 통계에서도 제외됩니다.")
    return redirect(request, "product_dashboard", product_id=review.product_id)


@app.post("/reviews/{review_id}/restore", name="review_restore")
def review_restore(request: Request,
                   review_id: int,
                   user: User = Depends(login_required),
                   db: Session = Depends(get_session)):
    review = _owned_review_or_404(db, user, review_id)
    if review.status != ReviewStatus.BLINDED:
        flash(request, "블라인드 상태인 리뷰가 아닙니다.", "error")
    else:
        review.status = ReviewStatus.VISIBLE
        review.blind_reason = review.blinded_by = review.blinded_at = None
        db.add(ReviewBlindLog(review=review, actor_id=user.id, action=BlindAction.RESTORE))
        db.commit()
        flash(request, "블라인드를 해제했습니다. 리뷰가 다시 목록과 통계에 포함됩니다.")
    return redirect(request, "product_dashboard", product_id=review.product_id)


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

    products = db.scalars(select(Product).where(Product.seller_id == user.id).order_by(Product.id)).all()

    return render(request, "analysis.html", active_menu="analysis", products=products,
                  stats=stat or {"visitors": 0, "buyers": 0},
                  rate_now=rate_now, rate_change=rate_change,
                  avg_rating=sum(r.rating for r in reviews) / len(reviews) if reviews else None,
                  review_count=len(reviews),
                  report=shop_report(reviews),
                  praise=praise, complaints=complaints,
                  positive_summary=positive_summary, negative_summary=negative_summary,
                  unreplied_risky=unreplied_risky, blinded_count=blinded_count)


# ──────────────────────────────────────────────
# CS챗봇 — 답글이 없는 리뷰 + 추천 답글 수정·복사·처리 완료  (cschatbot.html)
#   처리 완료 = 셀러가 쇼핑몰에 붙여넣은 최종 답글을 review_replies 에 저장
#   → 답글이 생긴 리뷰는 목록과 '위험 리뷰 n건'에서 빠진다 (ERD 변경 없음)
# ──────────────────────────────────────────────
CS_LIST_LIMIT = 30
REPLY_MAX_LENGTH = 2000      # API(ReplyCreate)와 같은 기준


@app.get("/cschatbot", name="cschatbot", response_class=HTMLResponse)
def cschatbot_page(request: Request,
                   user: User = Depends(login_required),
                   db: Session = Depends(get_session)):
    """아직 답글이 없는 리뷰를 위험도 높은 순 → 최신순으로 보여 주고, 리뷰마다 추천 답글 초안을 붙인다.
    셀러는 초안을 고친 뒤 '답글 복사하기'로 복사해 쇼핑몰(스마트스토어·쿠팡 등) 관리자 페이지에 붙여넣고,
    '처리 완료'를 눌러 목록에서 뺀다. (복사는 브라우저에서 처리)"""
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

    # 방금 처리 완료한 답글 → '되돌리기' 안내 (본인이 쓴 답글일 때만)
    done_param = request.query_params.get("done", "")
    just_done = _own_reply(db, user, int(done_param)) if done_param.isdigit() else None

    return render(request, "cschatbot.html", active_menu="cschatbot", rows=rows,
                  risky_unreplied=risky_unreplied, total_unreplied=total_unreplied,
                  list_limit=CS_LIST_LIMIT, just_done=just_done, reply_max_length=REPLY_MAX_LENGTH)


def _own_reply(db: Session, user: User, reply_id: int) -> Optional[ReviewReply]:
    """내 상품 리뷰에 내가 단 답글만 돌려줌 (아니면 None)"""
    reply = db.get(ReviewReply, reply_id)
    if reply is None or reply.author_id != user.id or reply.review.product.seller_id != user.id:
        return None
    return reply


@app.post("/cschatbot/done", name="cschatbot_done")
def cschatbot_done(request: Request,
                   review_id: str = Form(""),
                   content: str = Form(""),
                   user: User = Depends(login_required),
                   db: Session = Depends(get_session)):
    """처리 완료: 셀러가 (수정해서) 사용한 최종 답글을 저장 → CS챗봇 목록에서 빠짐"""
    content = content.strip()
    review = db.get(Review, int(review_id)) if review_id.isdigit() else None

    error = None
    if review is None or review.product.seller_id != user.id:
        error = "리뷰를 찾을 수 없습니다."
    elif review.status == ReviewStatus.BLINDED:
        error = "블라인드된 리뷰는 처리할 수 없습니다."
    elif not content:
        error = "답글 내용을 입력해 주세요."
    elif len(content) > REPLY_MAX_LENGTH:
        error = f"답글은 {REPLY_MAX_LENGTH:,}자 이하로 입력해 주세요."

    if error:
        flash(request, error, "error")
        return redirect(request, "cschatbot")

    reply = ReviewReply(review_id=review.id, author_id=user.id, content=content)
    db.add(reply)
    db.commit()
    return RedirectResponse(f"{request.url_for('cschatbot')}?done={reply.id}", status_code=303)


@app.post("/cschatbot/undo/{reply_id}", name="cschatbot_undo")
def cschatbot_undo(request: Request,
                   reply_id: int,
                   user: User = Depends(login_required),
                   db: Session = Depends(get_session)):
    """처리 완료 되돌리기: 저장한 답글을 지워 리뷰를 다시 목록에 표시"""
    reply = _own_reply(db, user, reply_id)
    if reply is None:
        flash(request, "되돌릴 답글을 찾을 수 없습니다.", "error")
    else:
        db.delete(reply)
        db.commit()
        flash(request, "처리 완료를 취소했습니다. 리뷰가 다시 목록에 표시됩니다.")
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
def my_risk_keywords(db: Session, user: User) -> list:
    return db.scalars(select(RiskKeyword).where(RiskKeyword.seller_id == user.id)
                      .order_by(RiskKeyword.weight.desc(), RiskKeyword.word)).all()


def render_settings(request: Request, db: Session, user: User, status_code: int = 200) -> HTMLResponse:
    return render(request, "informationedit.html", status_code=status_code, active_menu="settings",
                  risk_keywords=my_risk_keywords(db, user))


@app.get("/settings", name="settings", response_class=HTMLResponse)
def settings_page(request: Request,
                  user: User = Depends(login_required),
                  db: Session = Depends(get_session)):
    return render_settings(request, db, user)


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
        return render_settings(request, db, user, status_code=status)

    user.mall_name, user.mall_platform, user.business_number = mall_name, platform, biz
    if new_password:
        user.password_hash = hash_password(new_password)
    db.commit()
    flash(request, "회원정보가 저장되었습니다.")
    return redirect(request, "settings")


# ── 위험 키워드 관리 (설정 화면) — API(/api/v1/risk-keywords)와 같은 규칙
RISK_WORD_MAX = 100


@app.post("/settings/risk-keywords", name="risk_keyword_add")
def risk_keyword_add(request: Request,
                     word: str = Form(""),
                     weight: str = Form("2"),
                     user: User = Depends(login_required),
                     db: Session = Depends(get_session)):
    word = word.strip()
    level = int(weight) if weight.isdigit() else 0
    if not word:
        flash(request, "위험 키워드를 입력해 주세요.", "error")
    elif len(word) > RISK_WORD_MAX:
        flash(request, f"위험 키워드는 {RISK_WORD_MAX}자 이하로 입력해 주세요.", "error")
    elif not 1 <= level <= 10:
        flash(request, "위험도는 1~10 사이로 선택해 주세요.", "error")
    elif db.scalar(select(RiskKeyword.id).where(RiskKeyword.seller_id == user.id, RiskKeyword.word == word)):
        flash(request, f"'{word}'은(는) 이미 등록된 위험 키워드입니다.", "error")
    else:
        db.add(RiskKeyword(seller_id=user.id, word=word, weight=level))
        db.commit()
        flash(request, f"위험 키워드 '{word}'을(를) 추가했습니다. 기존 리뷰에 반영하려면 '기존 리뷰 다시 분석'을 눌러 주세요.")
    return RedirectResponse(f"{request.url_for('settings')}#risk-keywords", status_code=303)


@app.post("/settings/risk-keywords/{keyword_id}/delete", name="risk_keyword_delete")
def risk_keyword_delete(request: Request,
                        keyword_id: int,
                        user: User = Depends(login_required),
                        db: Session = Depends(get_session)):
    kw = db.get(RiskKeyword, keyword_id)
    if kw is None or kw.seller_id != user.id:
        flash(request, "위험 키워드를 찾을 수 없습니다.", "error")
    else:
        db.delete(kw)
        db.commit()
        flash(request, f"위험 키워드 '{kw.word}'을(를) 삭제했습니다.")
    return RedirectResponse(f"{request.url_for('settings')}#risk-keywords", status_code=303)


@app.post("/settings/reanalyze", name="reanalyze")
def reanalyze(request: Request,
              user: User = Depends(login_required),
              db: Session = Depends(get_session)):
    """현재 위험 키워드로 내 상품의 모든 리뷰(블라인드 포함)를 다시 분석"""
    keywords = seller_risk_keywords(db, user.id)
    reviews = db.scalars(select(Review).join(Review.product).where(Product.seller_id == user.id)
                         .options(selectinload(Review.analysis), selectinload(Review.keyword_links))).all()
    for review in reviews:
        analyze_and_save(db, review, keywords)
    db.commit()
    flash(request, f"리뷰 {len(reviews)}건을 현재 위험 키워드로 다시 분석했습니다.")
    return RedirectResponse(f"{request.url_for('settings')}#risk-keywords", status_code=303)


@app.post("/withdraw", name="withdraw")
def withdraw(request: Request,
             current_password: str = Form(""),
             user: User = Depends(login_required),
             db: Session = Depends(get_session)):
    """회원 탈퇴 (US-04, D5): 비밀번호 재확인 → 계정과 계정의 모든 데이터 삭제(하드 삭제) → 쿠키 만료"""
    if not verify_password(current_password, user.password_hash):
        flash(request, "비밀번호가 올바르지 않아 탈퇴할 수 없습니다.", "error")
        return render_settings(request, db, user, status_code=401)

    delete_account(db, user)
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
