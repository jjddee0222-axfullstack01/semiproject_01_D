"""
PIN POINT REVIEW - Flask 백엔드

실행:
    pip install -r requirements.txt
    python app.py
    → http://127.0.0.1:5000  (데모 계정: pinpoint_user / Pinpoint1!)
"""
import os
import re
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_db, is_risky_review

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    DATABASE=str(BASE_DIR / "instance" / "pinpoint.db"),
)
init_db(app)

# 비밀번호 규칙: 8자 이상, 영어 대문자/소문자/숫자/특수문자 각각 1개 이상
PASSWORD_RULE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")
# 사업자등록번호: 000-00-00000 (하이픈 생략 가능)
BUSINESS_NUM_RULE = re.compile(r"^\d{3}-?\d{2}-?\d{5}$")


# ──────────────────────────────────────────────
# 공통: 로그인 확인 / 템플릿 필터
# ──────────────────────────────────────────────
@app.before_request
def load_current_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None:          # 탈퇴 등으로 계정이 사라진 경우
            session.clear()


@app.context_processor
def inject_user():
    return {"current_user": g.get("user")}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.template_filter("mask_name")
def mask_name(name: str) -> str:
    """'김민수' → '김**'"""
    return name[0] + "*" * (len(name) - 1) if name else ""


@app.template_filter("dotdate")
def dotdate(value: str) -> str:
    """'2026-10-10 14:20:00' → '2026.10.10'"""
    return value[:10].replace("-", ".")


def normalize_business_num(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


# ──────────────────────────────────────────────
# 로그인 / 회원가입 / 로그아웃  (index.html, joinmembership.html)
# ──────────────────────────────────────────────
@app.route("/")
def index():
    return redirect(url_for("dashboard") if g.user else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        userid = request.form.get("userid", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE userid = ?", (userid,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))

    return render_template("index.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in
                ("name", "userid", "shop_name", "business_num")}
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        db = get_db()

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
            flash(error, "error")
            return render_template("joinmembership.html")

        db.execute(
            "INSERT INTO users (name, userid, password_hash, shop_name, business_num) "
            "VALUES (?, ?, ?, ?, ?)",
            (form["name"], form["userid"], generate_password_hash(password),
             form["shop_name"], normalize_business_num(form["business_num"])),
        )
        db.commit()
        flash("회원가입이 완료되었습니다. 로그인해주세요.", "success")
        return redirect(url_for("login"))

    return render_template("joinmembership.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("login"))


# ──────────────────────────────────────────────
# 대시보드  (dashboard.html)
# ──────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    risky_count = db.execute(
        "SELECT COUNT(*) FROM reviews r JOIN products p ON p.id = r.product_id "
        "WHERE p.user_id = ? AND r.is_risky = 1",
        (g.user["id"],),
    ).fetchone()[0]

    recent_reviews = db.execute(
        "SELECT r.* FROM reviews r JOIN products p ON p.id = r.product_id "
        "WHERE p.user_id = ? ORDER BY r.created_at DESC LIMIT 4",
        (g.user["id"],),
    ).fetchall()

    month = datetime.now().strftime("%Y-%m")
    stats = db.execute(
        "SELECT visitors, buyers FROM monthly_stats WHERE user_id = ? AND month = ?",
        (g.user["id"], month),
    ).fetchone() or {"visitors": 0, "buyers": 0}

    return render_template("dashboard.html", active_menu="dashboard",
                           risky_count=risky_count, recent_reviews=recent_reviews,
                           stats=stats)


# ──────────────────────────────────────────────
# 상품별 리뷰  (goodsreview.html)
# ──────────────────────────────────────────────
@app.route("/reviews")
@app.route("/reviews/<int:product_id>")
@login_required
def product_reviews(product_id=None):
    db = get_db()
    if product_id is None:
        product = db.execute(
            "SELECT * FROM products WHERE user_id = ? ORDER BY id LIMIT 1", (g.user["id"],)
        ).fetchone()
    else:
        product = db.execute(
            "SELECT * FROM products WHERE id = ? AND user_id = ?", (product_id, g.user["id"])
        ).fetchone()
        if product is None:
            abort(404)

    reviews, avg_rating = [], 0.0
    if product:
        reviews = db.execute(
            "SELECT * FROM reviews WHERE product_id = ? ORDER BY created_at DESC",
            (product["id"],),
        ).fetchall()
        if reviews:
            avg_rating = sum(r["rating"] for r in reviews) / len(reviews)

    return render_template("goodsreview.html", active_menu="reviews",
                           product=product, reviews=reviews, avg_rating=avg_rating)


@app.route("/api/reviews", methods=["POST"])
@login_required
def add_review():
    """리뷰 등록 (쇼핑몰 연동/테스트용 JSON API) — 등록 시 위험 리뷰 자동 판별"""
    data = request.get_json(silent=True) or {}
    try:
        product_id = int(data["product_id"])
        rating = int(data["rating"])
        author, content = str(data["author"]).strip(), str(data["content"]).strip()
    except (KeyError, ValueError, TypeError):
        return {"error": "product_id, author, content, rating 값이 필요합니다."}, 400
    if not (1 <= rating <= 5) or not author or not content:
        return {"error": "입력값이 올바르지 않습니다."}, 400

    db = get_db()
    owned = db.execute("SELECT 1 FROM products WHERE id = ? AND user_id = ?",
                       (product_id, g.user["id"])).fetchone()
    if not owned:
        return {"error": "상품을 찾을 수 없습니다."}, 404

    risky = is_risky_review(content, rating)
    cur = db.execute(
        "INSERT INTO reviews (product_id, author, content, rating, is_risky) VALUES (?, ?, ?, ?, ?)",
        (product_id, author, content, rating, int(risky)),
    )
    db.commit()
    return {"id": cur.lastrowid, "is_risky": risky}, 201


# ──────────────────────────────────────────────
# 설정 - 회원정보 수정 / 회원 탈퇴  (informationedit.html)
# ──────────────────────────────────────────────
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        shop_name = request.form.get("shop_name", "").strip()
        business_num = request.form.get("business_num", "").strip()

        error = None
        if not check_password_hash(g.user["password_hash"], current_password):
            error = "현재 비밀번호가 올바르지 않습니다."
        elif not shop_name or not business_num:
            error = "쇼핑몰 이름과 사업자번호를 입력해주세요."
        elif not BUSINESS_NUM_RULE.match(business_num):
            error = "사업자번호 형식이 올바르지 않습니다. (예: 123-45-67890)"
        elif new_password and not PASSWORD_RULE.match(new_password):
            error = "변경할 비밀번호는 8자 이상이며 영어 대/소문자, 숫자, 특수문자를 모두 포함해야 합니다."

        if error:
            flash(error, "error")
        else:
            db = get_db()
            password_hash = (generate_password_hash(new_password) if new_password
                             else g.user["password_hash"])
            db.execute(
                "UPDATE users SET shop_name = ?, business_num = ?, password_hash = ? WHERE id = ?",
                (shop_name, normalize_business_num(business_num), password_hash, g.user["id"]),
            )
            db.commit()
            flash("회원정보가 저장되었습니다.", "success")
            return redirect(url_for("settings"))

    return render_template("informationedit.html", active_menu="settings")


@app.route("/withdraw", methods=["POST"])
@login_required
def withdraw():
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    db.commit()
    session.clear()
    flash("회원 탈퇴가 완료되었습니다.", "success")
    return redirect(url_for("login"))


# ──────────────────────────────────────────────
# 의견 보내기  (sendfeedback.html)
# ──────────────────────────────────────────────
@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    if request.method == "POST":
        complaint = request.form.get("complaint", "").strip()
        suggestion = request.form.get("suggestion", "").strip()
        if not complaint and not suggestion:
            flash("내용을 하나 이상 입력해 주세요.", "error")
        else:
            db = get_db()
            db.execute("INSERT INTO feedback (user_id, complaint, suggestion) VALUES (?, ?, ?)",
                       (g.user["id"], complaint, suggestion))
            db.commit()
            flash("소중한 의견 감사합니다. 빠르게 검토하겠습니다.", "success")
            return redirect(url_for("feedback"))

    return render_template("sendfeedback.html", active_menu="feedback")


# ──────────────────────────────────────────────
# 404  (404page.html)
# ──────────────────────────────────────────────
@app.errorhandler(404)
def page_not_found(_error):
    return render_template("404page.html"), 404


if __name__ == "__main__":
    app.run(debug=True)
