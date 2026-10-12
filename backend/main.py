"""
PIN POINT REVIEW - FastAPI 백엔드

실행:
    pip install -r requirements.txt
    uvicorn main:app --reload
    → http://127.0.0.1:8000        (데모 계정: pinpoint_user / Pinpoint1!)
    → http://127.0.0.1:8000/docs   (API 문서 자동 생성)
"""
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from database import get_db, hash_password, init_db, is_risky_review, verify_password

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()            # 서버 시작 시 테이블 생성 + 데모 데이터
    yield


app = FastAPI(title="PIN POINT REVIEW", lifespan=lifespan)
app.add_middleware(SessionMiddleware,
                   secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"))

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 비밀번호 규칙: 8자 이상, 영어 대문자/소문자/숫자/특수문자 각각 1개 이상
PASSWORD_RULE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")
# 사업자등록번호: 000-00-00000 (하이픈 생략 가능)
BUSINESS_NUM_RULE = re.compile(r"^\d{3}-?\d{2}-?\d{5}$")


# ──────────────────────────────────────────────
# 템플릿 필터
# ──────────────────────────────────────────────
def mask_name(name: str) -> str:
    """'김민수' → '김**'"""
    return name[0] + "*" * (len(name) - 1) if name else ""


def dotdate(value: str) -> str:
    """'2026-10-10 14:20:00' → '2026.10.10'"""
    return value[:10].replace("-", ".")


templates.env.filters["mask_name"] = mask_name
templates.env.filters["dotdate"] = dotdate


def normalize_business_num(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


# ──────────────────────────────────────────────
# 플래시 메시지 (세션에 저장 → 다음 화면에서 1회 표시)
# ──────────────────────────────────────────────
def flash(request: Request, message: str, category: str = "success") -> None:
    request.session.setdefault("_flashes", []).append([category, message])


def pop_flashes(request: Request) -> list:
    return request.session.pop("_flashes", [])


def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    """모든 템플릿에 current_user / 플래시 메시지 / form(입력값 유지)을 함께 넘김"""
    flashes = pop_flashes(request)
    context.setdefault("form", {})
    context["current_user"] = getattr(request.state, "user", None)
    context["get_flashed_messages"] = lambda with_categories=False: (
        flashes if with_categories else [m for _, m in flashes])
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(request: Request, route_name: str, **path_params) -> RedirectResponse:
    # POST 처리 후에는 303으로 GET 화면에 이동 (새로고침 시 재전송 방지)
    return RedirectResponse(request.url_for(route_name, **path_params), status_code=303)


# ──────────────────────────────────────────────
# 로그인 사용자 의존성
# ──────────────────────────────────────────────
class LoginRequired(Exception):
    """로그인하지 않은 사용자가 보호된 화면에 접근"""


def get_current_user(request: Request, db: sqlite3.Connection = Depends(get_db)) -> Optional[sqlite3.Row]:
    user = None
    user_id = request.session.get("user_id")
    if user_id is not None:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:                 # 탈퇴 등으로 계정이 사라진 경우
            request.session.pop("user_id", None)
    request.state.user = user
    return user


def login_required(user: Optional[sqlite3.Row] = Depends(get_current_user)) -> sqlite3.Row:
    if user is None:
        raise LoginRequired()
    return user


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
          userid: str = Form(""),
          password: str = Form(""),
          db: sqlite3.Connection = Depends(get_db)):
    userid = userid.strip()
    user = db.execute("SELECT * FROM users WHERE userid = ?", (userid,)).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        flash(request, "아이디 또는 비밀번호가 올바르지 않습니다.", "error")
        return render(request, "index.html", status_code=400, form={"userid": userid})

    request.session.clear()
    request.session["user_id"] = user["id"]
    return redirect(request, "dashboard")


@app.get("/signup", name="signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return render(request, "joinmembership.html")


@app.post("/signup")
def signup(request: Request,
           name: str = Form(""),
           userid: str = Form(""),
           password: str = Form(""),
           password_confirm: str = Form(""),
           shop_name: str = Form(""),
           business_num: str = Form(""),
           db: sqlite3.Connection = Depends(get_db)):
    form = {"name": name.strip(), "userid": userid.strip(),
            "shop_name": shop_name.strip(), "business_num": business_num.strip()}

    error = None
    if not all(form.values()) or not password:
        error = "모든 항목을 입력해주세요."
    elif not re.fullmatch(r"[A-Za-z0-9_]{4,20}", form["userid"]):
        error = "아이디는 영문, 숫자, _ 조합 4~20자로 입력해주세요."
    elif not PASSWORD_RULE.match(password):
        error = "비밀번호는 8자 이상이며 영어 대/소문자, 숫자, 특수문자를 모두 포함해야 합니다."
    elif password != password_confirm:
        error = "비밀번호 확인이 일치하지 않습니다."
    elif not BUSINESS_NUM_RULE.match(form["business_num"]):
        error = "사업자 등록 번호 형식이 올바르지 않습니다. (예: 123-45-67890)"
    elif db.execute("SELECT 1 FROM users WHERE userid = ?", (form["userid"],)).fetchone():
        error = "이미 사용 중인 아이디입니다."

    if error:
        flash(request, error, "error")
        return render(request, "joinmembership.html", status_code=400, form=form)

    db.execute(
        "INSERT INTO users (name, userid, password_hash, shop_name, business_num) "
        "VALUES (?, ?, ?, ?, ?)",
        (form["name"], form["userid"], hash_password(password),
         form["shop_name"], normalize_business_num(form["business_num"])),
    )
    db.commit()
    flash(request, "회원가입이 완료되었습니다. 로그인해주세요.")
    return redirect(request, "login")


@app.get("/logout", name="logout")
def logout(request: Request):
    request.session.clear()
    flash(request, "로그아웃되었습니다.")
    return redirect(request, "login")


# ──────────────────────────────────────────────
# 대시보드  (dashboard.html)
# ──────────────────────────────────────────────
@app.get("/dashboard", name="dashboard", response_class=HTMLResponse)
def dashboard(request: Request,
              user=Depends(login_required),
              db: sqlite3.Connection = Depends(get_db)):
    risky_count = db.execute(
        "SELECT COUNT(*) FROM reviews r JOIN products p ON p.id = r.product_id "
        "WHERE p.user_id = ? AND r.is_risky = 1",
        (user["id"],),
    ).fetchone()[0]

    recent_reviews = db.execute(
        "SELECT r.* FROM reviews r JOIN products p ON p.id = r.product_id "
        "WHERE p.user_id = ? ORDER BY r.created_at DESC LIMIT 4",
        (user["id"],),
    ).fetchall()

    month = datetime.now().strftime("%Y-%m")
    stats = db.execute(
        "SELECT visitors, buyers FROM monthly_stats WHERE user_id = ? AND month = ?",
        (user["id"], month),
    ).fetchone() or {"visitors": 0, "buyers": 0}

    return render(request, "dashboard.html", active_menu="dashboard",
                  risky_count=risky_count, recent_reviews=recent_reviews, stats=stats)


# ──────────────────────────────────────────────
# 상품별 리뷰  (goodsreview.html)
# ──────────────────────────────────────────────
def _render_product_reviews(request: Request, db: sqlite3.Connection, product):
    reviews, avg_rating = [], 0.0
    if product:
        reviews = db.execute(
            "SELECT * FROM reviews WHERE product_id = ? ORDER BY created_at DESC",
            (product["id"],),
        ).fetchall()
        if reviews:
            avg_rating = sum(r["rating"] for r in reviews) / len(reviews)
    return render(request, "goodsreview.html", active_menu="reviews",
                  product=product, reviews=reviews, avg_rating=avg_rating)


@app.get("/reviews", name="product_reviews", response_class=HTMLResponse)
def product_reviews(request: Request,
                    user=Depends(login_required),
                    db: sqlite3.Connection = Depends(get_db)):
    """첫 번째 상품의 리뷰 화면"""
    product = db.execute(
        "SELECT * FROM products WHERE user_id = ? ORDER BY id LIMIT 1", (user["id"],)
    ).fetchone()
    return _render_product_reviews(request, db, product)


@app.get("/reviews/{product_id}", name="product_reviews_detail", response_class=HTMLResponse)
def product_reviews_detail(request: Request,
                           product_id: int,
                           user=Depends(login_required),
                           db: sqlite3.Connection = Depends(get_db)):
    product = db.execute(
        "SELECT * FROM products WHERE id = ? AND user_id = ?", (product_id, user["id"])
    ).fetchone()
    if product is None:
        raise HTTPException(status_code=404)
    return _render_product_reviews(request, db, product)


class ReviewIn(BaseModel):
    product_id: int
    author: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=2000)
    rating: int = Field(ge=1, le=5)


class ReviewOut(BaseModel):
    id: int
    is_risky: bool


@app.post("/api/reviews", status_code=201, response_model=ReviewOut)
def add_review(review: ReviewIn,
               user=Depends(login_required),
               db: sqlite3.Connection = Depends(get_db)):
    """리뷰 등록 (쇼핑몰 연동/테스트용 JSON API) — 등록 시 위험 리뷰 자동 판별"""
    owned = db.execute("SELECT 1 FROM products WHERE id = ? AND user_id = ?",
                       (review.product_id, user["id"])).fetchone()
    if not owned:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")

    risky = is_risky_review(review.content, review.rating)
    cur = db.execute(
        "INSERT INTO reviews (product_id, author, content, rating, is_risky) VALUES (?, ?, ?, ?, ?)",
        (review.product_id, review.author.strip(), review.content.strip(), review.rating, int(risky)),
    )
    db.commit()
    return ReviewOut(id=cur.lastrowid, is_risky=risky)


# ──────────────────────────────────────────────
# 설정 - 회원정보 수정 / 회원 탈퇴  (informationedit.html)
# ──────────────────────────────────────────────
@app.get("/settings", name="settings", response_class=HTMLResponse)
def settings_page(request: Request, user=Depends(login_required)):
    return render(request, "informationedit.html", active_menu="settings")


@app.post("/settings")
def settings(request: Request,
             current_password: str = Form(""),
             new_password: str = Form(""),
             shop_name: str = Form(""),
             business_num: str = Form(""),
             user=Depends(login_required),
             db: sqlite3.Connection = Depends(get_db)):
    shop_name, business_num = shop_name.strip(), business_num.strip()

    error = None
    if not verify_password(current_password, user["password_hash"]):
        error = "현재 비밀번호가 올바르지 않습니다."
    elif not shop_name or not business_num:
        error = "쇼핑몰 이름과 사업자번호를 입력해주세요."
    elif not BUSINESS_NUM_RULE.match(business_num):
        error = "사업자번호 형식이 올바르지 않습니다. (예: 123-45-67890)"
    elif new_password and not PASSWORD_RULE.match(new_password):
        error = "변경할 비밀번호는 8자 이상이며 영어 대/소문자, 숫자, 특수문자를 모두 포함해야 합니다."

    if error:
        flash(request, error, "error")
        return render(request, "informationedit.html", status_code=400, active_menu="settings")

    password_hash = hash_password(new_password) if new_password else user["password_hash"]
    db.execute(
        "UPDATE users SET shop_name = ?, business_num = ?, password_hash = ? WHERE id = ?",
        (shop_name, normalize_business_num(business_num), password_hash, user["id"]),
    )
    db.commit()
    flash(request, "회원정보가 저장되었습니다.")
    return redirect(request, "settings")


@app.post("/withdraw", name="withdraw")
def withdraw(request: Request,
             user=Depends(login_required),
             db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    db.commit()
    request.session.clear()
    flash(request, "회원 탈퇴가 완료되었습니다.")
    return redirect(request, "login")


# ──────────────────────────────────────────────
# 의견 보내기  (sendfeedback.html)
# ──────────────────────────────────────────────
@app.get("/feedback", name="feedback", response_class=HTMLResponse)
def feedback_page(request: Request, user=Depends(login_required)):
    return render(request, "sendfeedback.html", active_menu="feedback")


@app.post("/feedback")
def feedback(request: Request,
             complaint: str = Form(""),
             suggestion: str = Form(""),
             user=Depends(login_required),
             db: sqlite3.Connection = Depends(get_db)):
    complaint, suggestion = complaint.strip(), suggestion.strip()
    if not complaint and not suggestion:
        flash(request, "내용을 하나 이상 입력해 주세요.", "error")
        return render(request, "sendfeedback.html", status_code=400, active_menu="feedback")

    db.execute("INSERT INTO feedback (user_id, complaint, suggestion) VALUES (?, ?, ?)",
               (user["id"], complaint, suggestion))
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
    uvicorn.run("main:app", reload=True)
