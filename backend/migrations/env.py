"""Alembic 실행 환경 — 접속 정보와 테이블 정의를 서버 코드(db.py, models.py)에서 그대로 가져옴"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # noqa: E402  (backend/.env 를 읽어 DATABASE_URL 결정)
import models  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    """SQL 문만 출력 (python -m alembic upgrade head --sql)"""
    context.configure(url=db.DATABASE_URL.render_as_string(hide_password=False),
                      target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=db.IS_SQLITE)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    db._ensure_database()                     # MariaDB 에 DB 가 없으면 utf8mb4 로 생성 (서버 시작과 같은 동작)
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=db.IS_SQLITE)   # SQLite 는 ALTER 가 제한적이라 batch 모드
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
