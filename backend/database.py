"""
PIN POINT REVIEW - SQLite 데이터베이스 설정 / 비밀번호 해시 / 초기 데이터
"""
import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "pinpoint.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    userid        TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    shop_name     TEXT NOT NULL,
    business_num  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    category    TEXT,
    description TEXT,
    image_url   TEXT,
    positive_summary TEXT,   -- 비워두면 리뷰를 바탕으로 자동 요약 (AI 요약 결과를 저장해도 됨)
    negative_summary TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    author     TEXT NOT NULL,
    content    TEXT NOT NULL,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    is_risky   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS monthly_stats (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    month    TEXT NOT NULL,              -- 'YYYY-MM'
    visitors INTEGER NOT NULL DEFAULT 0,
    buyers   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, month)
);

CREATE TABLE IF NOT EXISTS product_stats (
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    month      TEXT NOT NULL,            -- 'YYYY-MM'
    buyers     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (product_id, month)
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    complaint  TEXT,
    suggestion TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# ──────────────────────────────────────────────
# 비밀번호 해시 (표준 라이브러리 PBKDF2-SHA256)
# ──────────────────────────────────────────────
_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(check.hex(), digest)


# 위험 리뷰 감지는 analysis.py 로 옮김 (기존 import 호환을 위해 다시 내보냄)
try:
    from .analysis import is_risky_review
except ImportError:
    from analysis import is_risky_review


# ──────────────────────────────────────────────
# DB 연결 (FastAPI 의존성으로 사용)
# ──────────────────────────────────────────────
def connect() -> sqlite3.Connection:
    # FastAPI는 의존성과 엔드포인트를 서로 다른 스레드에서 실행할 수 있으므로
    # check_same_thread=False 로 연결한다 (요청마다 새 연결이라 안전).
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """요청마다 DB 연결을 열고, 응답 후 닫는다"""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """테이블 생성 + DB가 비어 있으면 데모 데이터 입력"""
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate(conn)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        _seed(conn)
    conn.commit()
    conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """이전 버전으로 만든 DB에 새 컬럼을 추가 (데이터는 유지)"""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    for column in ("positive_summary", "negative_summary"):
        if column not in columns:
            conn.execute(f"ALTER TABLE products ADD COLUMN {column} TEXT")


def _seed(conn: sqlite3.Connection) -> None:
    """HTML 시안에 있던 예시 데이터를 그대로 넣어 둔 데모 계정"""
    cur = conn.execute(
        "INSERT INTO users (name, userid, password_hash, shop_name, business_num) "
        "VALUES (?, ?, ?, ?, ?)",
        ("홍길동", "pinpoint_user", hash_password("Pinpoint1!"),
         "피인포인트몰", "123-45-67890"),
    )
    user_id = cur.lastrowid

    # 상품 조회 / 상품별 대시보드 화면 시안의 예시 데이터
    demo = [
        ("[상품명] 프리미엄 시그니처 상품 A", "리빙", "옵션: 기본형 / 상세 설명이 제공되는 공간입니다.", 340, [
            ("김민수", "배송이 정말 빠르고 상품 마감 상태도 훌륭합니다. 대만족이에요!", 5, "2026-10-09 14:20:00"),
            ("이지은", "생각보다 색감이 조금 어둡긴 한데 전반적으로 쓸만합니다.", 3, "2026-10-08 10:05:00"),
            ("박서준", "포장이 살짝 찌그러져서 왔어요. 제품은 멀쩡합니다.", 3, "2026-10-07 18:42:00"),
            ("오세린", "선물용으로 구매했는데 포장도 깔끔하고 품질이 고급스러워요.", 5, "2026-10-05 09:30:00"),
            ("강도윤", "불량품이 왔어요. 환불 요청합니다.", 1, "2026-10-02 13:00:00"),
        ]),
        ("[상품명] 에센셜 베이직 아이템 B", "패션", "옵션: S / M / L", 520, [
            ("최유리", "배송도 빠르고 상품 상태가 너무 마음에 듭니다! 파손 없이 잘 왔어요.", 5, "2026-10-12 09:12:00"),
            ("정하늘", "생각했던 것보다 조금 아쉽네요. 마감 처리가 살짝 헐거워요.", 3, "2026-10-11 21:30:00"),
            ("윤서아", "설명과 완전히 다른 제품이에요. 사기 아닌가요? 소비자원에 신고하겠습니다.", 1, "2026-10-04 16:45:00"),
        ]),
        ("[상품명] 컴포트 데일리 상품 C", "생활", "옵션: 1개입 / 3개입", 420, [
            ("한지호", "가성비 최고입니다. 주변에도 추천했어요! 재구매 의사 있습니다.", 5, "2026-10-10 11:20:00"),
            ("서도현", "크기가 딱 적당하고 배송도 빨랐어요.", 4, "2026-10-06 15:10:00"),
            ("문가은", "포장 상자가 찢어져서 왔고 구성품 하나가 누락됐습니다.", 2, "2026-10-03 11:20:00"),
        ]),
    ]
    for name, category, description, buyers, reviews in demo:
        product_id = conn.execute(
            "INSERT INTO products (user_id, name, category, description) VALUES (?, ?, ?, ?)",
            (user_id, name, category, description),
        ).lastrowid
        conn.executemany(
            "INSERT INTO reviews (product_id, author, content, rating, is_risky, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(product_id, a, c, r, int(is_risky_review(c, r)), t) for a, c, r, t in reviews],
        )
        conn.execute(
            "INSERT INTO product_stats (product_id, month, buyers) "
            "VALUES (?, strftime('%Y-%m', 'now', 'localtime'), ?)",
            (product_id, buyers),
        )

    conn.execute(
        "INSERT INTO monthly_stats (user_id, month, visitors, buyers) "
        "VALUES (?, strftime('%Y-%m', 'now', 'localtime'), ?, ?)",
        (user_id, 12450, 1280),
    )
