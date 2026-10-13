"""
PIN POINT REVIEW - SQLAlchemy 엔진 / 세션 설정 (MariaDB)

접속 정보는 backend/.env 파일(또는 환경 변수)에서 읽습니다.  → .env.example 참고
    DB_HOST=127.0.0.1
    DB_PORT=3306
    DB_USER=pinpoint
    DB_PASSWORD=비밀번호
    DB_NAME=pinpoint

DATABASE_URL 을 직접 지정하면 위 값 대신 그것을 사용합니다 (예: 테스트용 sqlite:///test.db).
"""
import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

try:
    from .models import Base
except ImportError:
    from models import Base

BASE_DIR = Path(__file__).resolve().parent


# ──────────────────────────────────────────────
# .env 읽기 (추가 패키지 없이). 이미 설정된 환경 변수는 덮어쓰지 않음
# ──────────────────────────────────────────────
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_env_file(BASE_DIR / ".env")


def _database_url() -> URL:
    if os.environ.get("DATABASE_URL"):
        return make_url(os.environ["DATABASE_URL"])
    # URL.create 는 비밀번호에 @ : / 같은 특수문자가 있어도 안전하게 처리
    return URL.create(
        "mariadb+pymysql",
        username=os.environ.get("DB_USER", "pinpoint"),
        password=os.environ.get("DB_PASSWORD", ""),
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        database=os.environ.get("DB_NAME", "pinpoint"),
        query={"charset": "utf8mb4"},          # 한글·이모지 리뷰
    )


DATABASE_URL: URL = _database_url()
IS_SQLITE = DATABASE_URL.get_backend_name() == "sqlite"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # 끊긴 연결 자동 감지 (MariaDB wait_timeout 대비)
    pool_recycle=3600,       # 1시간마다 연결 교체
    # SQLite(테스트용): FastAPI가 의존성과 엔드포인트를 다른 스레드에서 실행할 수 있으므로 허용
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_conn, _record):
    """SQLite는 기본으로 FK(ON DELETE CASCADE / SET NULL)가 꺼져 있으므로 켠다 (MariaDB는 해당 없음)"""
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


def describe_db() -> str:
    """로그 출력용 접속 정보 (비밀번호는 ***)"""
    return DATABASE_URL.render_as_string(hide_password=True)


def get_session() -> Iterator[Session]:
    """FastAPI 의존성:  def api(db: Session = Depends(get_session)): ..."""
    with SessionLocal() as session:
        yield session


def _ensure_database() -> None:
    """MariaDB에 DB_NAME 데이터베이스가 없으면 utf8mb4 로 생성 (권한이 없으면 건너뜀)"""
    if IS_SQLITE or not DATABASE_URL.database:
        return
    server_engine = create_engine(DATABASE_URL.set(database=""), pool_pre_ping=True)
    try:
        with server_engine.connect() as conn:
            conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{DATABASE_URL.database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    except OperationalError as exc:
        # 1044/1227: 권한 없음 → DB는 setup_mariadb.sql 로 미리 만들어 두었다고 보고 계속 진행
        if exc.orig is None or exc.orig.args[0] not in (1044, 1227):
            raise
    finally:
        server_engine.dispose()


def create_tables() -> None:
    """데이터베이스·테이블 생성 (이미 있는 테이블은 그대로 둠)

    운영 중 컬럼 변경이 생기면 create_all 로는 반영되지 않으므로 Alembic 마이그레이션 사용을 권장
    """
    if IS_SQLITE and DATABASE_URL.database:
        Path(DATABASE_URL.database).parent.mkdir(parents=True, exist_ok=True)
    try:
        _ensure_database()
        Base.metadata.create_all(engine)
    except OperationalError as exc:
        raise RuntimeError(
            "\n[DB 연결 실패] MariaDB에 접속할 수 없습니다: " + describe_db() +
            "\n  1) MariaDB 서비스가 실행 중인지 확인하세요 (Windows: 서비스 → MariaDB)" +
            "\n  2) backend/.env 의 DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME 을 확인하세요" +
            "\n  3) 계정·DB가 없다면 backend/setup_mariadb.sql 을 root 계정으로 한 번 실행하세요" +
            f"\n  원인: {exc.orig}"
        ) from None


if __name__ == "__main__":
    print("접속:", describe_db())
    create_tables()
    print("테이블 생성 완료:", ", ".join(sorted(Base.metadata.tables)))
