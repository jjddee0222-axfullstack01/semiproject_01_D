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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

# backend 폴더 안에서 실행(main:app)하든, 최상위 폴더에서 실행(backend.main:app)하든 동작
try:
    from .analysis import RISK_SEVERITY, shop_report, summarize_reviews
    from .api_v1 import setup_api
    from .auth import (LoginRequired, clear_cookie, delete_account, end_all_sessions, end_other_sessions, end_session,
                       get_current_user, login_required, start_session)
    from . import rate_limit
    from .email_verify import (PURPOSES, MailUnavailable, check_code, issue_code, mail_config_warning,
                               show_code_on_screen, verification_enabled)
    from .database import (add_default_risk_keywords, init_db, last_month, reanalyze_seller_reviews,
                           this_month)
    from .db import describe_db, get_session
    from .models import (BlindAction, Feedback, IngestLog, IssueType, Keyword, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                         ReviewAnalysis, ReviewBlindLog, ReviewKeyword, ProductAction, ReplyTemplate, ReviewMemo, MemoStatus, ReviewReply, ReviewStatus, RiskKeyword, ShopMonthlyStat, User,
                         UserStatus, visible_reviews)
    from .pipeline import IngestError, decode_csv_bytes, ingest_rows, parse_csv_text, parse_xlsx_bytes
    from .alerts import (compose_risk_mail, deliver, last_review_id, risk_email_enabled, risky_reviews_after,
                             set_risk_email)
    from .insights import REPORT_PERIODS, SURGE_DAYS, SURGE_MIN_COUNT, SURGE_RATIO, keyword_surges, period_report
    from .privacy import mask_pii
    from .onboarding import SAMPLE_PREFIX, has_sample, load_sample, remove_sample
    from .seller_tools import (ACTION_WINDOW_DAYS, MISMATCH_CUES, OVERDUE_DAYS,
                               action_effect, action_problem, best_reviews, detail_tips, mismatch_condition,
                                    mismatch_count, product_actions, response_stats, strengths)
    from .reply_drafts import (SENTIMENT_LABELS as TEMPLATE_LABELS, TEMPLATE_MAX_LENGTH, TEMPLATE_PLACEHOLDERS, seller_reply_draft,
                                   seller_templates, template_problem)
    from .schemas import EMAIL_PATTERN, PASSWORD_MESSAGE, PASSWORD_PATTERN
    from .security import hash_password, verify_password
except ImportError:
    from analysis import RISK_SEVERITY, shop_report, summarize_reviews
    from api_v1 import setup_api
    from auth import (LoginRequired, clear_cookie, delete_account, end_all_sessions, end_other_sessions, end_session,
                      get_current_user, login_required, start_session)
    import rate_limit
    from email_verify import (PURPOSES, MailUnavailable, check_code, issue_code, mail_config_warning,
                              show_code_on_screen, verification_enabled)
    from database import (add_default_risk_keywords, init_db, last_month, reanalyze_seller_reviews,
                          this_month)
    from db import describe_db, get_session
    from models import (BlindAction, Feedback, IngestLog, IssueType, Keyword, MallPlatform, Polarity, Product, ProductMonthlyStat, Review,
                        ReviewAnalysis, ReviewBlindLog, ReviewKeyword, ProductAction, ReplyTemplate, ReviewMemo, MemoStatus, ReviewReply, ReviewStatus, RiskKeyword, ShopMonthlyStat, User,
                        UserStatus, visible_reviews)
    from pipeline import IngestError, decode_csv_bytes, ingest_rows, parse_csv_text, parse_xlsx_bytes
    from alerts import (compose_risk_mail, deliver, last_review_id, risk_email_enabled, risky_reviews_after,
                            set_risk_email)
    from insights import REPORT_PERIODS, SURGE_DAYS, SURGE_MIN_COUNT, SURGE_RATIO, keyword_surges, period_report
    from privacy import mask_pii
    from onboarding import SAMPLE_PREFIX, has_sample, load_sample, remove_sample
    from seller_tools import (ACTION_WINDOW_DAYS, MISMATCH_CUES, OVERDUE_DAYS,
                              action_effect, action_problem, best_reviews, detail_tips, mismatch_condition,
                                   mismatch_count, product_actions, response_stats, strengths)
    from reply_drafts import (SENTIMENT_LABELS as TEMPLATE_LABELS, TEMPLATE_MAX_LENGTH, TEMPLATE_PLACEHOLDERS, seller_reply_draft,
                                  seller_templates, template_problem)
    from schemas import EMAIL_PATTERN, PASSWORD_MESSAGE, PASSWORD_PATTERN
    from security import hash_password, verify_password

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    print(f"[PIN POINT] DB: {describe_db()}")
    if warning := rate_limit.secret_key_warning(os.environ.get("SECRET_KEY", "")):
        print(warning)
    if warning := mail_config_warning():
        print(warning)
    init_db()            # 서버 시작 시 테이블 생성 + (비어 있으면) 데모 데이터
    yield


app = FastAPI(title="PIN POINT REVIEW", lifespan=lifespan)

# 로그인은 sessions 테이블 + session_id 쿠키로 처리하고,
# 이 미들웨어(서명 쿠키 pp_flash)는 화면 안내 메시지 전달에만 사용
app.add_middleware(SessionMiddleware, session_cookie="pp_flash",
                   secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"))

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ── 입력 규칙
#    화면과 REST API 가 같은 규칙을 쓰도록 schemas.py 의 정의를 그대로 사용 (예전에는 화면만 '8자 이상', API 는 '8~64자')
PASSWORD_RULE = PASSWORD_PATTERN
EMAIL_RULE = EMAIL_PATTERN
PASSWORD_RULE_MSG = PASSWORD_MESSAGE
#    DB 컬럼 크기 (models.py 와 같게). 넘는 값을 그대로 저장하면 MariaDB 에서 오류(500)가 나므로 먼저 막는다
FIELD_MAX = {"name": ("이름", 50), "email": ("이메일", 255), "mall_name": ("쇼핑몰 이름", 100)}


def too_long(form: dict) -> Optional[str]:
    """form 값 중 DB 컬럼 길이를 넘는 것이 있으면 안내 문구, 없으면 None"""
    for key, (label, limit) in FIELD_MAX.items():
        if key in form and len(form[key]) > limit:
            return f"{label}은(는) {limit}자 이하로 입력해 주세요."
    return None


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


templates.env.filters.update(mask_name=mask_name, dotdate=dotdate, bizno=bizno,
                             pii=mask_pii)        # v1.2 리뷰 속 전화번호·이메일 가리기 (privacy.py)


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
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


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
    ip = rate_limit.client_ip(request)
    # 같은 이메일 5번 / 같은 IP 20번 틀리면 10분 잠금 (서버에 기록 → 쿠키를 지워도 유지)
    if locked := rate_limit.login_locked_seconds(email, ip):
        flash(request, rate_limit.lock_message(locked), "error")
        return render(request, "index.html", status_code=429, form={"email": email})
    user = db.scalar(select(User).where(User.email == email))
    if (user is None or user.status != UserStatus.ACTIVE
            or not verify_password(password, user.password_hash)):
        left = rate_limit.login_failed(email, ip)
        if left == 0:
            message = rate_limit.lock_message(rate_limit.LOGIN_LOCK_SECONDS)
        elif left <= 2:
            message = (f"이메일 또는 비밀번호가 올바르지 않습니다. "
                       f"({left}번 더 틀리면 {rate_limit.LOGIN_LOCK_SECONDS // 60}분 동안 잠깁니다)")
        else:
            message = "이메일 또는 비밀번호가 올바르지 않습니다."
        flash(request, message, "error")
        return render(request, "index.html", status_code=401, form={"email": email})

    rate_limit.login_succeeded(email)
    response = redirect(request, "dashboard")
    start_session(db, user, response)
    return response


# ──────────────────────────────────────────────
# 이메일 인증 코드  (회원가입 · 비밀번호 변경 화면에서 fetch 로 호출, email_verify.py)
# ──────────────────────────────────────────────
@app.post("/email-code", name="email_code")
async def email_code(request: Request, db: Session = Depends(get_session)):
    """{purpose: signup|reset, email} → {ok, message, dev_code?}"""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    purpose = str(body.get("purpose", ""))
    email = str(body.get("email", "")).strip().lower()
    if purpose not in PURPOSES:
        return JSONResponse({"ok": False, "message": "잘못된 요청입니다."}, status_code=400)
    if not EMAIL_RULE.match(email):
        return JSONResponse({"ok": False, "message": "이메일 형식이 올바르지 않습니다."}, status_code=400)

    existing = db.scalar(select(User).where(User.email == email))
    if purpose == "signup" and existing is not None:
        return JSONResponse({"ok": False, "message": "이미 가입된 이메일입니다."}, status_code=409)
    # 비밀번호 변경: 가입되지 않은 이메일이어도 같은 안내를 보여 줌 (가입 여부 노출 방지, 메일은 보내지 않음)
    deliver = purpose == "signup" or (existing is not None and existing.status == UserStatus.ACTIVE)
    try:
        ok, message, dev_code = issue_code(purpose, email, deliver=deliver, ip=rate_limit.client_ip(request))
    except MailUnavailable as exc:              # 운영 모드인데 메일 서버 미설정
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=503)
    payload = {"ok": ok, "message": message}
    if dev_code:
        payload["dev_code"] = dev_code          # 개발 모드(메일 서버 미설정)에서만
    return JSONResponse(payload, status_code=200 if ok else 429)


def email_context() -> dict:
    """회원가입·비밀번호 변경 템플릿에 넘기는 이메일 인증 설정"""
    return {"email_verification": verification_enabled(), "mail_dev_mode": show_code_on_screen()}


# ──────────────────────────────────────────────
# 비밀번호 변경하기 — 로그인 전 '비밀번호 찾기'  (passwordreset.html, Figma: 비밀번호 변경하기)
#   이름 + 이메일(+인증 코드) + 사업자 등록 번호가 모두 일치하면 새 비밀번호로 변경
#   5번 틀리면 10분 잠금, 변경 후에는 모든 기기에서 로그아웃
# ──────────────────────────────────────────────
RESET_MAX_FAILS = rate_limit.RESET_MAX_FAILS          # 이 횟수만큼 틀리면
RESET_LOCK_SECONDS = rate_limit.RESET_LOCK_SECONDS    # 이 시간 동안 잠금 (이메일·IP 기준, 서버에 기록)


def render_reset(request: Request, status_code: int = 200, form: Optional[dict] = None) -> HTMLResponse:
    return render(request, "passwordreset.html", status_code=status_code, form=form or {}, **email_context())


@app.get("/password-reset", name="password_reset", response_class=HTMLResponse)
def password_reset_page(request: Request):
    return render_reset(request)


@app.post("/password-reset")
def password_reset(request: Request,
                   name: str = Form(""),
                   email: str = Form(""),
                   email_code: str = Form(""),
                   new_password: str = Form(""),
                   new_password_confirm: str = Form(""),
                   business_number: str = Form(""),
                   db: Session = Depends(get_session)):
    form = {"name": name.strip(), "email": email.strip().lower(), "business_number": business_number.strip()}
    lock_keys = (f"email:{form['email']}", f"ip:{rate_limit.client_ip(request)}")
    if locked := rate_limit.password_reset.locked_for(*lock_keys):
        minutes = max(1, (locked + 59) // 60)
        flash(request, f"정보가 여러 번 일치하지 않아 잠겼습니다. {minutes}분 뒤에 다시 시도해 주세요.", "error")
        return render_reset(request, 429, form)

    if not all(form.values()) or not new_password:
        flash(request, "모든 항목을 입력해 주세요.", "error")
        return render_reset(request, 400, form)
    if not PASSWORD_RULE.match(new_password):
        flash(request, "변경할 " + PASSWORD_RULE_MSG, "error")
        return render_reset(request, 400, form)
    if new_password != new_password_confirm:
        flash(request, "비밀번호 확인이 일치하지 않습니다.", "error")
        return render_reset(request, 400, form)
    code_error = check_code("reset", form["email"], email_code)
    if code_error:
        flash(request, code_error, "error")
        return render_reset(request, 400, form)

    biz = normalize_business_number(form["business_number"])
    user = db.scalar(select(User).where(User.email == form["email"], User.status == UserStatus.ACTIVE))
    # 세 값이 모두 일치해야 함. 어느 값이 틀렸는지는 알려 주지 않음 (계정 존재 여부 노출 방지)
    if user is None or user.name != form["name"] or biz is None or user.business_number != biz:
        count = rate_limit.password_reset.fail(*lock_keys)
        if count >= RESET_MAX_FAILS:
            flash(request, f"정보가 {RESET_MAX_FAILS}번 일치하지 않아 {RESET_LOCK_SECONDS // 60}분 동안 잠깁니다.", "error")
        else:
            flash(request, "입력한 정보와 일치하는 계정이 없습니다. 이름, 이메일, 사업자 등록 번호를 확인해 주세요. "
                           f"({count}/{RESET_MAX_FAILS})", "error")
        return render_reset(request, 400, form)

    if verify_password(new_password, user.password_hash):
        flash(request, "지금 쓰는 비밀번호와 다른 비밀번호를 입력해 주세요.", "error")
        return render_reset(request, 400, form)

    user.password_hash = hash_password(new_password)
    end_all_sessions(db, user)              # 다른 기기에 남아 있는 로그인도 모두 종료
    db.commit()
    rate_limit.password_reset.reset(*lock_keys)
    rate_limit.login_succeeded(form["email"])           # 비밀번호를 바꿨으면 로그인 잠금도 해제
    response = redirect(request, "login")
    clear_cookie(response)
    flash(request, "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요.")
    return response


@app.get("/signup", name="signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return render(request, "joinmembership.html", **email_context())


@app.post("/signup")
def signup(request: Request,
           name: str = Form(""),
           email: str = Form(""),
           password: str = Form(""),
           password_confirm: str = Form(""),
           mall_name: str = Form(""),
           mall_platform: str = Form(""),
           business_number: str = Form(""),
           email_code: str = Form(""),
           db: Session = Depends(get_session)):
    form = {"name": name.strip(), "email": email.strip().lower(), "mall_name": mall_name.strip(),
            "mall_platform": mall_platform, "business_number": business_number.strip()}
    platform = parse_platform(mall_platform)
    biz = normalize_business_number(form["business_number"])

    error, status = None, 400
    if not all(form.values()) or not password:
        error = "모든 항목을 입력해주세요."
    elif length_error := too_long(form):
        error = length_error
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
    else:
        code_error = check_code("signup", form["email"], email_code)
        if code_error:
            error = code_error

    if error:
        flash(request, error, "error")
        return render(request, "joinmembership.html", status_code=status, form=form, **email_context())

    user = User(name=form["name"], email=form["email"], password_hash=hash_password(password),
                mall_name=form["mall_name"], mall_platform=platform, business_number=biz)
    db.add(user)
    add_default_risk_keywords(db, user)
    db.commit()
    flash(request, "회원가입이 완료되었습니다. 로그인해주세요.")
    return redirect(request, "login")


@app.get("/logout")
def logout_get(request: Request, user=Depends(get_current_user)):
    """GET 으로는 로그아웃하지 않음 (다른 사이트가 <img src=".../logout"> 등으로 몰래 로그아웃시키는 것 방지)"""
    return redirect(request, "dashboard" if user else "login")


@app.post("/logout", name="logout")
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

    has_products = db.scalar(select(Product.id).where(Product.seller_id == user.id).limit(1)) is not None
    return render(request, "dashboard.html", active_menu="dashboard",
                  risky_count=risky_count, recent_reviews=recent_reviews, stats=stats,
                  todo=dashboard_todo(db, user), surges=keyword_surges(db, user.id),
                  response=response_stats(db, user.id),                       # v1.2 답글 응답 시간
                  has_products=has_products, has_sample=has_sample(db, user))  # v1.2 처음 쓰는 셀러 안내


# ── v1.2 샘플 데이터로 체험하기 (대시보드) — 이름이 '[샘플] ' 로 시작하는 상품으로 넣고 한 번에 지움
@app.post("/onboarding/sample", name="sample_load")
def sample_load(request: Request,
                user: User = Depends(login_required),
                db: Session = Depends(get_session)):
    added = load_sample(db, user)
    flash(request, f"샘플 리뷰 {added}건을 넣었습니다. 대시보드·상품 조회·CS챗봇을 둘러보세요. 다 보신 뒤 대시보드에서 지울 수 있습니다."
          if added else "샘플 데이터가 이미 들어 있습니다.")
    return redirect(request, "dashboard")


@app.post("/onboarding/sample/delete", name="sample_delete")
def sample_delete(request: Request,
                  user: User = Depends(login_required),
                  db: Session = Depends(get_session)):
    count = remove_sample(db, user)
    db.commit()
    flash(request, f"샘플 상품 {count}개와 리뷰를 모두 지웠습니다." if count else "지울 샘플 데이터가 없습니다.")
    return redirect(request, "dashboard")


def dashboard_todo(db: Session, user: User) -> list[dict]:
    """대시보드 '처리할 일' 카드 — 지금 손봐야 할 일과 바로 가는 링크 (건수가 0인 일도 '완료'로 표시)"""
    mine = visible_reviews().join(Review.product).where(Product.seller_id == user.id)
    count = lambda stmt: db.scalar(stmt.with_only_columns(func.count(Review.id))) or 0
    week_ago = date.today() - timedelta(days=6)

    unreplied_risky = count(mine.join(Review.analysis).where(ReviewAnalysis.severity >= RISK_SEVERITY,
                                                            ~Review.replies.any()))
    unreplied = count(mine.where(~Review.replies.any()))
    negative_week = count(mine.join(Review.analysis).where(ReviewAnalysis.sentiment == Polarity.NEG,
                                                          Review.reviewed_at >= week_ago))
    last_upload = db.scalar(select(IngestLog.run_at).where(IngestLog.batch_name.startswith(f"upload:{user.id}:"))
                            .order_by(IngestLog.run_at.desc()).limit(1))
    has_products = db.scalar(select(Product.id).where(Product.seller_id == user.id).limit(1)) is not None
    return [
        {"label": "답글이 필요한 위험 리뷰", "count": unreplied_risky, "unit": "건", "urgent": True,
         "url": "cschatbot", "query": "", "action": "CS챗봇에서 답글 달기"},
        {"label": "최근 7일 부정 리뷰", "count": negative_week, "unit": "건", "urgent": False,
         "url": "review_list", "query": "sentiment=NEG&period=7", "action": "리뷰 목록에서 보기"},
        {"label": "아직 답글이 없는 리뷰", "count": unreplied, "unit": "건", "urgent": False,
         "url": "review_list", "query": "replied=no", "action": "리뷰 목록에서 보기"},
        {"label": "리뷰 데이터 업로드",
         "count": 0 if has_products else 1, "unit": "",
         "note": (f"마지막 업로드 {last_upload:%Y.%m.%d}" if last_upload else "아직 업로드 기록이 없습니다"),
         "urgent": False, "url": "products", "query": "", "action": "CSV 업로드하기"},
    ]


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
    neutral = func.sum(case((ReviewAnalysis.sentiment == Polarity.NEU, 1), else_=0))
    risky = func.sum(case((ReviewAnalysis.severity >= RISK_SEVERITY, 1), else_=0))
    rows = db.execute(
        select(Product,
               func.count(Review.id).label("review_count"),
               func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
               func.coalesce(positive, 0).label("positive_count"),
               func.coalesce(negative, 0).label("negative_count"),
               func.coalesce(neutral, 0).label("neutral_count"),
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
              "negative_count": int(neg), "neutral_count": int(neu), "risky_count": int(rk)}
             for p, n, avg, pos, neg, neu, rk in rows]
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
                          background_tasks: BackgroundTasks,
                          file: Optional[UploadFile] = File(None),
                          user: User = Depends(login_required),
                          db: Session = Depends(get_session)):
    """리뷰 CSV·엑셀(.xlsx) 업로드 → 상품이 없으면 새로 만들고, 리뷰를 적재한 뒤 바로 분석 (중복·오류 행은 건너뜀)"""
    filename = (file.filename or "").strip() if file else ""
    lower = filename.lower()
    error = None
    if not filename:
        error = "업로드할 CSV 또는 엑셀(.xlsx) 파일을 선택해 주세요."
    elif lower.endswith(".xls"):
        error = "예전 엑셀 형식(.xls)은 읽을 수 없습니다. 엑셀에서 '다른 이름으로 저장 → Excel 통합 문서(.xlsx)' 또는 CSV로 저장해 주세요."
    elif not lower.endswith((".csv", ".xlsx")):
        error = "CSV(.csv) 또는 엑셀(.xlsx) 파일만 업로드할 수 있습니다."
    else:
        data = await file.read(UPLOAD_MAX_BYTES + 1)
        if len(data) > UPLOAD_MAX_BYTES:
            error = f"파일이 너무 큽니다. {UPLOAD_MAX_BYTES // (1024 * 1024)}MB 이하로 나눠서 올려 주세요."
        else:
            try:
                rows = parse_xlsx_bytes(data) if lower.endswith(".xlsx") else parse_csv_text(decode_csv_bytes(data))
            except (IngestError, csv.Error) as exc:
                error = f"파일을 읽을 수 없습니다: {exc}"
            else:
                if not rows:
                    error = "헤더 아래에 리뷰 데이터가 없습니다."
                elif len(rows) > UPLOAD_MAX_ROWS:
                    error = f"한 번에 {UPLOAD_MAX_ROWS:,}행까지 올릴 수 있습니다. (현재 {len(rows):,}행)"

    if error:
        flash(request, error, "error")
        return redirect(request, "products")

    before_id = last_review_id(db, user.id)
    log, problems = ingest_rows(db, batch_name=f"upload:{user.id}:{filename}", rows=rows, seller=user)
    added = log.total_count - log.duplicate_count - log.missing_count
    message = f"'{filename}' 업로드 완료: 리뷰 {added:,}건 추가"
    if log.duplicate_count:
        message += f", 중복 {log.duplicate_count:,}건 제외"
    if log.missing_count:
        shown = ", ".join(problems[:5]) + (f" 외 {len(problems) - 5}건" if len(problems) > 5 else "")
        message += f", 오류 {log.missing_count:,}건 건너뜀 ({shown})"
    flash(request, message + ".", "success" if added else "error")

    # v1.1 위험 리뷰 알림: 새로 들어온 위험 리뷰 안내 + (설정했으면) 응답 후 백그라운드로 메일
    risky = risky_reviews_after(db, user.id, before_id) if added else []
    if risky:
        notice = f"새로 들어온 리뷰 중 위험 리뷰 {len(risky):,}건이 있습니다. CS챗봇에서 먼저 확인해 주세요."
        if risk_email_enabled(db, user.id):
            subject, body = compose_risk_mail(user, risky, filename)
            background_tasks.add_task(deliver, user.email, subject, body)
            notice += " (알림 메일 발송)"
        flash(request, notice, "error")
    return redirect(request, "products")


# ──────────────────────────────────────────────
# 업로드 이력  ※ /products/{product_id} 보다 먼저 등록해야 함 — 상품 조회 화면의 CSV 업로드 기록  (uploads.html)
#   ingest_logs 에 셀러 컬럼이 없어 batch_name 'upload:{셀러ID}:{파일명}' 으로 구분 (DB 구조 변경 없음)
# ──────────────────────────────────────────────
UPLOAD_HISTORY_LIMIT = 100


@app.get("/products/uploads", name="upload_history", response_class=HTMLResponse)
def upload_history(request: Request,
                   user: User = Depends(login_required),
                   db: Session = Depends(get_session)):
    prefix = f"upload:{user.id}:"
    logs = db.scalars(select(IngestLog).where(IngestLog.batch_name.startswith(prefix, autoescape=True))
                      .order_by(IngestLog.run_at.desc(), IngestLog.id.desc()).limit(UPLOAD_HISTORY_LIMIT)).all()
    rows = [{"run_at": log.run_at, "filename": log.batch_name[len(prefix):], "total": log.total_count,
             "added": log.total_count - log.duplicate_count - log.missing_count,
             "duplicate": log.duplicate_count, "missing": log.missing_count} for log in logs]
    totals = {k: sum(r[k] for r in rows) for k in ("total", "added", "duplicate", "missing")}
    return render(request, "uploads.html", active_menu="products", rows=rows, totals=totals,
                  limit=UPLOAD_HISTORY_LIMIT)


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
    return apply_review_filters(stmt, filters)


def apply_review_filters(stmt, filters: dict):
    """감성·이슈·위험·평점·검색어 필터 (상품별 대시보드와 리뷰 목록 화면 공용). ReviewAnalysis 가 조인돼 있어야 함"""
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
    if filters.get("mismatch"):                       # v1.2 별점·내용 불일치 (4~5점인데 아쉬움·불만)
        stmt = stmt.where(mismatch_condition())
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

    # v1.2 개선 조치(전후 비교) · 상세페이지 보완 포인트 · 별점·내용 불일치
    actions = [{"action": a, "effect": action_effect(db, a)} for a in product_actions(db, product_id)]

    return render(request, "productdashboard.html", active_menu="products",
                  actions=actions, tips=detail_tips(db, user.id, product_id),
                  action_marks=[{"month": a["action"].action_date.strftime("%Y-%m"), "label": a["action"].title[:12]}
                                for a in actions],
                  mismatch=mismatch_count(db, user.id, product_id), today=date.today(),
                  product=product, reviews=reviews, risky_count=risky_count, blinded_reviews=blinded_reviews,
                  avg_rating=avg_rating, monthly_buyers=stat.buyers if stat else 0,
                  positive_summary=positive_summary, negative_summary=negative_summary,
                  filters=filters, active_filters=active_filters, total_reviews=len(all_reviews),
                  filtered_total=filtered_total, page=page, pages=pages,
                  sentiment_labels=SENTIMENT_LABELS, issue_labels=ISSUE_LABELS,
                  severity_labels=SEVERITY_LABELS,
                  sort_labels={k: label for k, (label, _) in REVIEW_SORTS.items()})


# ── v1.2 상품 개선 조치 기록 (상품별 대시보드) — API(/api/v1/products/{id}/actions)와 같은 규칙
def parse_iso_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


@app.post("/products/{product_id}/actions", name="product_action_add")
def product_action_add(request: Request,
                       product_id: int,
                       action_date: str = Form(""),
                       title: str = Form(""),
                       issue: str = Form(""),
                       user: User = Depends(login_required),
                       db: Session = Depends(get_session)):
    product = db.get(Product, product_id)
    if product is None or product.seller_id != user.id:
        raise HTTPException(status_code=404)
    title, when = title.strip(), parse_iso_date(action_date)
    if problem := action_problem(title, when):
        flash(request, problem, "error")
    else:
        db.add(ProductAction(product_id=product.id, action_date=when, title=title,
                             issue_type=IssueType(issue) if issue in ISSUE_LABELS else None))
        db.commit()
        flash(request, f"개선 조치 '{title}'을(를) 기록했습니다. 조치 전후 리뷰를 비교해 보여 드립니다.")
    return RedirectResponse(f"{request.url_for('product_dashboard', product_id=product_id)}#actions", status_code=303)


@app.post("/products/{product_id}/actions/{action_id}/delete", name="product_action_delete")
def product_action_delete(request: Request,
                          product_id: int,
                          action_id: int,
                          user: User = Depends(login_required),
                          db: Session = Depends(get_session)):
    action = db.get(ProductAction, action_id)
    if action is None or action.product_id != product_id or action.product.seller_id != user.id:
        raise HTTPException(status_code=404)
    db.delete(action)
    db.commit()
    flash(request, "개선 조치 기록을 삭제했습니다.")
    return RedirectResponse(f"{request.url_for('product_dashboard', product_id=product_id)}#actions", status_code=303)


# ──────────────────────────────────────────────
# 리뷰 목록 — 모든 상품의 리뷰를 한 곳에서 검색·필터  (reviews.html)
# ──────────────────────────────────────────────
REVIEW_LIST_PAGE_SIZE = 20
REVIEW_PERIODS = {"7": "최근 7일", "30": "최근 30일", "90": "최근 3개월", "365": "최근 1년"}


@app.get("/reviews", name="review_list", response_class=HTMLResponse)
def review_list(request: Request,
                product_id: str = "",
                sentiment: str = "",
                issue: str = "",
                risk: str = "",
                rating: str = "",
                q: str = "",
                sort: str = "latest",
                period: str = "",
                replied: str = "",
                status: str = "",
                mismatch: str = "",
                memo: str = "",
                page: str = "1",
                user: User = Depends(login_required),
                db: Session = Depends(get_session)):
    """내 모든 상품의 리뷰 — 상품·감성·이슈·위험·평점·기간·답글 여부·블라인드·검색어 필터 + 정렬 + 페이지"""
    products = db.scalars(select(Product).where(Product.seller_id == user.id).order_by(Product.id)).all()
    product_ids = {str(p.id) for p in products}

    filters = review_filters(sentiment, issue, risk, rating, q, sort)
    filters.update({
        "product_id": product_id if product_id in product_ids else "",        # 남의 상품 ID 는 무시
        "period": period if period in REVIEW_PERIODS else "",
        "replied": replied if replied in ("yes", "no") else "",
        "status": "BLINDED" if status == "BLINDED" else "",
        "mismatch": "1" if mismatch == "1" else "",                          # v1.2 별점·내용 불일치
        "memo": memo if memo in MEMO_STATUS_LABELS or memo == "NONE" else "",  # v1.2 내부 처리 상태
    })

    stmt = (select(Review).join(Review.product)
            .outerjoin(ReviewAnalysis, ReviewAnalysis.review_id == Review.id)
            .where(Product.seller_id == user.id,
                   Review.status == (ReviewStatus.BLINDED if filters["status"] else ReviewStatus.VISIBLE)))
    stmt = apply_review_filters(stmt, filters)
    if filters["product_id"]:
        stmt = stmt.where(Review.product_id == int(filters["product_id"]))
    if filters["period"]:
        stmt = stmt.where(Review.reviewed_at >= date.today() - timedelta(days=int(filters["period"]) - 1))
    if filters["replied"]:
        stmt = stmt.where(Review.replies.any() if filters["replied"] == "yes" else ~Review.replies.any())
    if filters["memo"] == "NONE":
        stmt = stmt.where(~select(ReviewMemo.review_id).where(ReviewMemo.review_id == Review.id).exists())
    elif filters["memo"]:
        stmt = stmt.where(select(ReviewMemo.review_id).where(ReviewMemo.review_id == Review.id,
                                                            ReviewMemo.status == MemoStatus(filters["memo"])).exists())

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    pages = max(1, -(-total // REVIEW_LIST_PAGE_SIZE))
    page = min(max(int(page) if page.isdigit() else 1, 1), pages)
    reviews = db.scalars(
        stmt.options(selectinload(Review.analysis), selectinload(Review.product), selectinload(Review.replies),
                     selectinload(Review.memo))
        .order_by(*REVIEW_SORTS[filters["sort"]][1]())
        .limit(REVIEW_LIST_PAGE_SIZE).offset((page - 1) * REVIEW_LIST_PAGE_SIZE)
    ).all()
    active_filters = {k: v for k, v in filters.items() if v and not (k == "sort" and v == "latest")}

    return render(request, "reviews.html", active_menu="reviews", reviews=reviews, products=products,
                  filters=filters, active_filters=active_filters, total=total, page=page, pages=pages,
                  sentiment_labels=SENTIMENT_LABELS, issue_labels=ISSUE_LABELS, severity_labels=SEVERITY_LABELS,
                  period_labels=REVIEW_PERIODS, memo_labels=MEMO_STATUS_LABELS, memo_max=MEMO_MAX_LENGTH,
                  current_url=str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
                  sort_labels={k: label for k, (label, _) in REVIEW_SORTS.items()})


# ── v1.2 리뷰 내부 메모 · 처리 상태 (리뷰 목록) — API(/api/v1/reviews/{id}/memo)와 같은 규칙
MEMO_STATUS_LABELS = {"TODO": "확인 필요", "IN_PROGRESS": "처리 중", "DONE": "처리 완료"}
MEMO_MAX_LENGTH = 1000


def _safe_next(value: str, fallback: str) -> str:
    """되돌아갈 주소는 우리 사이트의 리뷰 목록만 허용 (다른 사이트로 보내는 오픈 리다이렉트 방지)"""
    return value if value.startswith("/reviews") and "//" not in value and "\\" not in value else fallback


@app.post("/reviews/{review_id}/memo", name="review_memo_save")
def review_memo_save(request: Request,
                     review_id: int,
                     status: str = Form("TODO"),
                     memo: str = Form(""),
                     next: str = Form(""),
                     user: User = Depends(login_required),
                     db: Session = Depends(get_session)):
    review = _owned_review_or_404(db, user, review_id)
    memo = memo.replace("\r\n", "\n").strip()
    back = _safe_next(next, str(request.url_for("review_list")))
    if status not in MEMO_STATUS_LABELS:
        flash(request, "처리 상태를 선택해 주세요.", "error")
    elif len(memo) > MEMO_MAX_LENGTH:
        flash(request, f"메모는 {MEMO_MAX_LENGTH:,}자 이하로 입력해 주세요.", "error")
    else:
        row = review.memo or ReviewMemo(review_id=review.id)
        row.status, row.memo, row.updated_by = MemoStatus(status), memo or None, user.id
        db.add(row)
        db.commit()
        flash(request, f"리뷰 #{review.id} 상태를 '{MEMO_STATUS_LABELS[status]}'(으)로 저장했습니다.")
    return RedirectResponse(f"{back}#review-{review_id}", status_code=303)


@app.post("/reviews/{review_id}/memo/delete", name="review_memo_delete")
def review_memo_delete(request: Request,
                       review_id: int,
                       next: str = Form(""),
                       user: User = Depends(login_required),
                       db: Session = Depends(get_session)):
    review = _owned_review_or_404(db, user, review_id)
    if review.memo is not None:
        db.delete(review.memo)
        db.commit()
    flash(request, f"리뷰 #{review.id} 메모를 지웠습니다.")
    return RedirectResponse(_safe_next(next, str(request.url_for("review_list"))), status_code=303)


# ──────────────────────────────────────────────
# 상품 비교 (FR-15, US-17) — 두 상품의 평점·감성·이슈·키워드를 나란히  (compare.html)
# ──────────────────────────────────────────────
def product_profile(db: Session, user: User, product: Product) -> dict:
    """비교 화면 한 칸에 들어가는 상품 요약 (공개 리뷰 기준)"""
    reviews = db.scalars(visible_reviews().where(Review.product_id == product.id)
                         .options(selectinload(Review.analysis))).all()
    analyzed = [r for r in reviews if r.analysis]
    n = len(reviews)
    pos = sum(1 for r in analyzed if r.analysis.sentiment == Polarity.POS)
    neg = sum(1 for r in analyzed if r.analysis.sentiment == Polarity.NEG)
    neu = sum(1 for r in analyzed if r.analysis.sentiment == Polarity.NEU)
    issues = {label: sum(1 for r in analyzed if r.analysis.issue_type and r.analysis.issue_type.value == key)
              for key, label in ISSUE_LABELS.items()}
    keyword_rows = db.execute(
        select(Keyword.word, Keyword.polarity, func.count(ReviewKeyword.review_id))
        .join(ReviewKeyword, ReviewKeyword.keyword_id == Keyword.id)
        .join(Review, Review.id == ReviewKeyword.review_id)
        .where(Review.product_id == product.id, Review.status == ReviewStatus.VISIBLE)
        .group_by(Keyword.id, Keyword.word, Keyword.polarity)
        .order_by(func.count(ReviewKeyword.review_id).desc(), Keyword.word).limit(5)
    ).all()
    stat = db.get(ProductMonthlyStat, (product.id, this_month()))
    return {
        "product": product, "review_count": n,
        "avg_rating": sum(r.rating for r in reviews) / n if n else None,
        "positive": pos, "negative": neg, "neutral": neu, "analyzed": len(analyzed),
        "neutral_ratio": neu / len(analyzed) if analyzed else 0,
        "positive_ratio": pos / len(analyzed) if analyzed else 0, "negative_ratio": neg / len(analyzed) if analyzed else 0,
        "risky": sum(1 for r in analyzed if r.analysis.severity >= RISK_SEVERITY),
        "issues": issues, "keywords": keyword_rows, "buyers": stat.buyers if stat else 0,
    }


def compare_summary(a: dict, b: dict) -> list[str]:
    """두 상품의 차이를 문장으로"""
    lines = []
    name_a, name_b = a["product"].name, b["product"].name
    if a["avg_rating"] is not None and b["avg_rating"] is not None:
        diff = a["avg_rating"] - b["avg_rating"]
        if abs(diff) < 0.05:
            lines.append("두 상품의 평균 평점이 비슷합니다.")
        else:
            hi, lo = (name_a, name_b) if diff > 0 else (name_b, name_a)
            lines.append(f"'{hi}'의 평균 평점이 '{lo}'보다 {abs(diff):.1f}점 높습니다.")
    if a["analyzed"] and b["analyzed"]:
        diff = (a["negative_ratio"] - b["negative_ratio"]) * 100
        if abs(diff) >= 5:
            hi = name_a if diff > 0 else name_b
            lines.append(f"'{hi}'의 부정 리뷰 비율이 {abs(diff):.0f}%p 더 높습니다.")
    for prof, other in ((a, b), (b, a)):
        top = max(prof["issues"].items(), key=lambda kv: kv[1])
        if top[1] and top[1] > other["issues"][top[0]]:
            lines.append(f"'{prof['product'].name}'은(는) '{top[0]}' 관련 불만이 더 많습니다.")
    return lines or ["두 상품 모두 아직 비교할 만한 리뷰가 많지 않습니다."]


@app.get("/compare", name="compare_products", response_class=HTMLResponse)
def compare_products(request: Request,
                     a: str = "",
                     b: str = "",
                     user: User = Depends(login_required),
                     db: Session = Depends(get_session)):
    products = db.scalars(select(Product).where(Product.seller_id == user.id).order_by(Product.id)).all()
    by_id = {str(p.id): p for p in products}
    if len(products) < 2:
        return render(request, "compare.html", active_menu="analysis", products=products, left=None, right=None,
                      summary=[])
    # 지정하지 않았거나 남의 상품이면 앞의 두 상품. 같은 상품 둘을 고르면 두 번째를 다른 상품으로
    pa = by_id.get(a) or products[0]
    pb = by_id.get(b) or next(p for p in products if p.id != pa.id)
    if pb.id == pa.id:
        pb = next(p for p in products if p.id != pa.id)
        flash(request, "서로 다른 두 상품을 골라 주세요.", "error")
    left, right = product_profile(db, user, pa), product_profile(db, user, pb)
    return render(request, "compare.html", active_menu="analysis", products=products,
                  left=left, right=right, summary=compare_summary(left, right))


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


# ──────────────────────────────────────────────
# v1.1 주간 / 월간 리포트  (reports.html) — 'PDF로 저장' 은 브라우저 인쇄(window.print) 사용
# ──────────────────────────────────────────────
@app.get("/reports", name="reports", response_class=HTMLResponse)
def reports_page(request: Request,
                 period: str = "week",
                 user: User = Depends(login_required),
                 db: Session = Depends(get_session)):
    report = period_report(db, user.id, period)
    return render(request, "reports.html", active_menu="reports", report=report, periods=REPORT_PERIODS,
                  generated_at=datetime.now())


# ──────────────────────────────────────────────
# v1.2 리뷰 활용 (marketing.html) — 베스트 리뷰 · 강점 키워드 · 소개 문구
# ──────────────────────────────────────────────
@app.get("/marketing", name="marketing", response_class=HTMLResponse)
def marketing_page(request: Request,
                   product_id: str = "",
                   user: User = Depends(login_required),
                   db: Session = Depends(get_session)):
    products = db.scalars(select(Product).where(Product.seller_id == user.id).order_by(Product.id)).all()
    selected = next((p for p in products if str(p.id) == product_id), None)       # 남의 상품 ID 는 전체로
    pid = selected.id if selected else None
    return render(request, "marketing.html", active_menu="marketing", products=products, selected=selected,
                  best=best_reviews(db, user.id, pid), strength=strengths(db, user.id, pid))


# ──────────────────────────────────────────────
# v1.2 도움말 (help.html) — 분석 기준·용어·업로드 형식 (숫자는 코드의 상수를 그대로 보여 줌)
# ──────────────────────────────────────────────
@app.get("/help", name="help_page", response_class=HTMLResponse)
def help_page(request: Request, user: User = Depends(login_required)):
    return render(request, "help.html", active_menu="help", risk_severity=RISK_SEVERITY,
                  surge_days=SURGE_DAYS, surge_min=SURGE_MIN_COUNT, surge_ratio=SURGE_RATIO,
                  overdue_days=OVERDUE_DAYS, mismatch_cues=MISMATCH_CUES, action_days=ACTION_WINDOW_DAYS,
                  placeholders=TEMPLATE_PLACEHOLDERS, upload_mb=UPLOAD_MAX_BYTES // (1024 * 1024),
                  upload_rows=UPLOAD_MAX_ROWS, sample_prefix=SAMPLE_PREFIX.strip())


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

    templates_ = seller_templates(db, user.id)          # v1.1 셀러 답글 템플릿 (없으면 기본 초안)
    rows = [{"review": r, "draft": seller_reply_draft(r, user, templates_)[0]} for r in reviews]

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
    elif review.replies:                          # 두 번 누르기·뒤로 가기 후 다시 제출 → 답글 중복 방지
        error = "이미 처리 완료된 리뷰입니다."
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
# 설정 - 회원정보 수정 / 회원 탈퇴  (informationedit.html)
# ──────────────────────────────────────────────
def my_risk_keywords(db: Session, user: User) -> list:
    return db.scalars(select(RiskKeyword).where(RiskKeyword.seller_id == user.id)
                      .order_by(RiskKeyword.weight.desc(), RiskKeyword.word)).all()


TEMPLATE_EXAMPLES = {
    Polarity.POS: "예) 안녕하세요 {고객명} 고객님, {쇼핑몰명}입니다. {상품명}을(를) 좋게 봐 주셔서 감사합니다!",
    Polarity.NEU: "예) {기본 답글}\n다음 구매 때 쓰실 수 있는 쿠폰을 쪽지로 보내 드렸어요.",
    Polarity.NEG: "예) {기본 답글}\n담당자 직통: 1:1 문의 → '빠른 처리' 선택",
}


def render_settings(request: Request, db: Session, user: User, status_code: int = 200) -> HTMLResponse:
    saved = seller_templates(db, user.id)
    reply_templates = [{"sentiment": p.value, "label": TEMPLATE_LABELS[p], "example": TEMPLATE_EXAMPLES[p],
                        "content": saved[p].content if p in saved else ""}
                       for p in (Polarity.NEG, Polarity.NEU, Polarity.POS)]
    return render(request, "informationedit.html", status_code=status_code, active_menu="settings",
                  risk_keywords=my_risk_keywords(db, user), risk_email=risk_email_enabled(db, user.id),
                  reply_templates=reply_templates, template_placeholders=TEMPLATE_PLACEHOLDERS,
                  template_max_length=TEMPLATE_MAX_LENGTH)


@app.get("/settings", name="settings", response_class=HTMLResponse)
def settings_page(request: Request,
                  user: User = Depends(login_required),
                  db: Session = Depends(get_session)):
    return render_settings(request, db, user)


@app.post("/settings")
def settings(request: Request,
             current_password: str = Form(""),
             new_password: str = Form(""),
             new_password_confirm: str = Form(""),
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
    elif length_error := too_long({"mall_name": mall_name}):
        error = length_error
    elif platform is None:
        error = "쇼핑몰 플랫폼을 선택해주세요."
    elif biz is None:
        error = "사업자번호는 숫자 10자리로 입력해주세요. (예: 123-45-67890)"
    elif db.scalar(select(User.id).where(User.business_number == biz, User.id != user.id)):
        error, status = "이미 다른 계정에 등록된 사업자번호입니다.", 409
    elif new_password and not PASSWORD_RULE.match(new_password):
        error = "변경할 " + PASSWORD_RULE_MSG
    elif new_password and new_password != new_password_confirm:
        error = "변경할 비밀번호와 비밀번호 확인이 일치하지 않습니다."

    if error:
        flash(request, error, "error")
        return render_settings(request, db, user, status_code=status)

    user.mall_name, user.mall_platform, user.business_number = mall_name, platform, biz
    if new_password:
        user.password_hash = hash_password(new_password)
        end_other_sessions(db, user, request)      # 다른 기기에 남은 로그인은 끊고 지금 화면만 유지
    db.commit()
    flash(request, "회원정보가 저장되었습니다." + (" 다른 기기의 로그인은 모두 종료했습니다." if new_password else ""))
    return redirect(request, "settings")


# ── 위험 키워드 관리 (설정 화면) — API(/api/v1/risk-keywords)와 같은 규칙
RISK_WORD_MAX = 100


def applied_message(word: str, count: int) -> str:
    """키워드 변경 후 자동 재분석 결과 안내"""
    if count:
        return f"'{word}'이(가) 들어간 리뷰 {count}건에 바로 반영했습니다."
    return f"아직 '{word}'이(가) 들어간 리뷰는 없습니다. 앞으로 들어오는 리뷰부터 적용됩니다."


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
        db.flush()                                   # 추가한 키워드까지 포함해 바로 재분석
        count = reanalyze_seller_reviews(db, user.id, [word])
        db.commit()
        flash(request, f"위험 키워드 '{word}'을(를) 추가했습니다. {applied_message(word, count)}")
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
        word = kw.word
        db.delete(kw)
        db.flush()                                   # 삭제한 키워드를 빼고 바로 재분석
        count = reanalyze_seller_reviews(db, user.id, [word])
        db.commit()
        flash(request, f"위험 키워드 '{word}'을(를) 삭제했습니다. {applied_message(word, count)}")
    return RedirectResponse(f"{request.url_for('settings')}#risk-keywords", status_code=303)


@app.post("/settings/reanalyze", name="reanalyze")
def reanalyze(request: Request,
              user: User = Depends(login_required),
              db: Session = Depends(get_session)):
    """현재 위험 키워드로 내 상품의 모든 리뷰(블라인드 포함)를 다시 분석"""
    count = reanalyze_seller_reviews(db, user.id)
    db.commit()
    flash(request, f"리뷰 {count}건을 현재 위험 키워드로 다시 분석했습니다.")
    return RedirectResponse(f"{request.url_for('settings')}#risk-keywords", status_code=303)


# ── v1.1 알림 설정 / 답글 템플릿 (설정 화면) — API(/api/v1/users/me/notifications, /api/v1/reply-templates)와 같은 규칙
@app.post("/settings/notifications", name="notification_settings")
def notification_settings(request: Request,
                          risk_email: str = Form(""),
                          user: User = Depends(login_required),
                          db: Session = Depends(get_session)):
    enabled = risk_email == "1"
    set_risk_email(db, user.id, enabled)
    db.commit()
    flash(request, "위험 리뷰 메일 알림을 " + ("켰습니다." if enabled else "껐습니다."))
    return RedirectResponse(f"{request.url_for('settings')}#notifications", status_code=303)


def _template_sentiment(value: str) -> Optional[Polarity]:
    try:
        return Polarity(value)
    except ValueError:
        return None


@app.post("/settings/reply-templates/{sentiment}", name="reply_template_save")
def reply_template_save(request: Request,
                        sentiment: str,
                        content: str = Form(""),
                        user: User = Depends(login_required),
                        db: Session = Depends(get_session)):
    polarity = _template_sentiment(sentiment)
    content = content.replace("\r\n", "\n").strip()
    if polarity is None:
        flash(request, "템플릿 종류를 찾을 수 없습니다.", "error")
    elif not content:                                # 비우고 저장 = 기본 초안으로 되돌리기
        return reply_template_reset(request, sentiment, user, db)
    elif problem := template_problem(content):
        flash(request, problem, "error")
    else:
        template = seller_templates(db, user.id).get(polarity) or ReplyTemplate(seller_id=user.id, sentiment=polarity)
        template.content = content
        db.add(template)
        db.commit()
        flash(request, f"{TEMPLATE_LABELS[polarity]} 리뷰 답글 템플릿을 저장했습니다. CS챗봇 초안에 바로 적용됩니다.")
    return RedirectResponse(f"{request.url_for('settings')}#reply-templates", status_code=303)


@app.post("/settings/reply-templates/{sentiment}/reset", name="reply_template_reset")
def reply_template_reset(request: Request,
                         sentiment: str,
                         user: User = Depends(login_required),
                         db: Session = Depends(get_session)):
    polarity = _template_sentiment(sentiment)
    if polarity is None:
        flash(request, "템플릿 종류를 찾을 수 없습니다.", "error")
    else:
        template = seller_templates(db, user.id).get(polarity)
        if template is not None:
            db.delete(template)
            db.commit()
        flash(request, f"{TEMPLATE_LABELS[polarity]} 리뷰 답글을 기본 초안으로 되돌렸습니다.")
    return RedirectResponse(f"{request.url_for('settings')}#reply-templates", status_code=303)


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

    response = redirect(request, "withdrawn")
    clear_cookie(response)
    request.session["withdrawn"] = True       # 탈퇴 완료 화면을 한 번만 보여 주기 위한 표시
    return response


@app.get("/withdrawn", name="withdrawn", response_class=HTMLResponse)
def withdrawn_page(request: Request):
    """회원 탈퇴 완료 (Figma: 회원 탈퇴가 완료되었습니다 / 처음으로 돌아가기). 탈퇴 직후가 아니면 로그인 화면으로"""
    if not request.session.pop("withdrawn", False):
        return redirect(request, "login")
    return render(request, "withdrawn.html")


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
        flash(request, "불편 사항과 기타 제안 사항을 모두 입력해 주세요.", "error")
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
# 화면 주소의 경로 값이 잘못되면(/products/abc) JSON 오류 대신 404 화면. API 는 기존 형식({code, message}) 유지
_api_validation_handler = app.exception_handlers[RequestValidationError]


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if not request.url.path.startswith("/api/") and any(e.get("loc", ("",))[0] == "path" for e in exc.errors()):
        return render(request, "404page.html", status_code=404)
    return await _api_validation_handler(request, exc)


# 너무 큰 ID(/products/99999999999999999999)는 DB 정수 범위를 넘으므로 '없음(404)'으로 처리
@app.exception_handler(OverflowError)
async def overflow_handler(request: Request, _exc: OverflowError):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"code": "NOT_FOUND", "message": "요청한 항목을 찾을 수 없습니다."}, status_code=404)
    return render(request, "404page.html", status_code=404)


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
