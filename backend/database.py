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
    image_url   TEXT
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


# ──────────────────────────────────────────────
# 위험 리뷰 감지 (간단한 규칙 기반 — 추후 AI 모델로 교체 가능)
# ──────────────────────────────────────────────
RISK_KEYWORDS = [
    "환불", "사기", "신고", "고소", "최악", "불량", "파손", "누락",
    "곰팡이", "벌레", "다쳤", "부작용", "소비자원", "짝퉁", "가품",
]


def is_risky_review(content: str, rating: int) -> bool:
    """평점이 낮거나 위험 키워드가 포함되면 위험 리뷰로 판단"""
    if rating <= 2:
        return True
    # '파손 없이'처럼 부정형으로 쓰인 경우는 제외
    text = content.replace("파손 없이", "").replace("파손없이", "")
    return any(keyword in text for keyword in RISK_KEYWORDS)


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
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        _seed(conn)
    conn.commit()
    conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    """HTML 시안에 있던 예시 데이터를 그대로 넣어 둔 데모 계정"""
    cur = conn.execute(
        "INSERT INTO users (name, userid, password_hash, shop_name, business_num) "
        "VALUES (?, ?, ?, ?, ?)",
        ("홍길동", "pinpoint_user", hash_password("Pinpoint1!"),
         "피인포인트몰", "123-45-67890"),
    )
    user_id = cur.lastrowid

    cur = conn.execute(
        "INSERT INTO products (user_id, name, category, description) VALUES (?, ?, ?, ?)",
        (user_id, "[상품명] 프리미엄 시그니처 상품", "리빙",
         "옵션: 기본형 / 상품 상세 설명이 들어가는 영역입니다."),
    )
    product_id = cur.lastrowid

    reviews = [
        ("김민수", "배송도 엄청 빠르고 실물이 훨씬 고급스럽네요! 아주 만족스럽게 잘 쓰고 있습니다.", 5, "2026-10-10 14:20:00"),
        ("이지은", "선물용으로 구매했는데 포장도 깔끔하고 받는 분이 좋아하셨어요. 재구매 의사 있습니다!", 5, "2026-10-09 10:05:00"),
        ("박서준", "생각했던 것보다 크기가 딱 적당해서 마음에 듭니다. 번창하세요~", 5, "2026-10-08 18:42:00"),
        ("최유리", "배송도 빠르고 상품 상태가 너무 마음에 듭니다! 파손 없이 잘 왔어요.", 5, "2026-10-07 09:12:00"),
        ("정하늘", "생각했던 것보다 조금 아쉽네요. 마감 처리가 살짝 헐거워요.", 3, "2026-10-06 21:30:00"),
        ("강도윤", "불량품이 왔어요. 환불 요청합니다.", 1, "2026-10-05 13:00:00"),
        ("윤서아", "설명과 완전히 다른 제품이에요. 사기 아닌가요? 소비자원에 신고하겠습니다.", 1, "2026-10-04 16:45:00"),
        ("한지호", "포장 상자가 찢어져서 왔고 구성품 하나가 누락됐습니다.", 2, "2026-10-03 11:20:00"),
    ]
    conn.executemany(
        "INSERT INTO reviews (product_id, author, content, rating, is_risky, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(product_id, a, c, r, int(is_risky_review(c, r)), t) for a, c, r, t in reviews],
    )

    conn.execute(
        "INSERT INTO monthly_stats (user_id, month, visitors, buyers) "
        "VALUES (?, strftime('%Y-%m', 'now', 'localtime'), ?, ?)",
        (user_id, 12450, 1280),
    )
