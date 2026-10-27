"""Alembic 마이그레이션 (v1.1) — 빈 DB · 서버가 create_all 로 만든 기존 DB 모두 'upgrade head' 가능해야 함

다른 테스트와 DB 가 섞이지 않도록 임시 SQLite 파일을 만들어 별도 프로세스로 alembic 을 실행
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("alembic")

BACKEND_DIR = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.unit


def _run(db_path, *args, code=None):
    # 출력은 UTF-8 로 주고받음 (한국어 Windows 콘솔 기본값 cp949 로 읽다가 깨지지 않게)
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + db_path.as_posix(), "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, "-c", code] if code else [sys.executable, "-m", "alembic", *args]
    return subprocess.run(cmd, cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def _tables(db_path):
    import sqlite3
    with sqlite3.connect(db_path) as con:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_alembic_files_readable_on_korean_windows():
    """Alembic 은 alembic.ini 를 OS 기본 인코딩(한국어 Windows = cp949)으로 읽음 → ASCII 만 써야 함.
    마이그레이션 첫 줄(실행 로그에 찍히는 제목)도 cp949 로 출력할 수 없는 문자(— 등)가 없어야 함 (2026-10-28 PC 에서 실패)"""
    ini = (BACKEND_DIR / "alembic.ini").read_bytes()
    assert ini.isascii(), "alembic.ini 에 한글 등 ASCII 가 아닌 글자가 있습니다"
    for path in (BACKEND_DIR / "migrations" / "versions").glob("*.py"):
        title = path.read_text(encoding="utf-8").split("\n", 1)[0]
        assert title.isascii(), f"{path.name} 첫 줄은 영문으로: {title}"


def test_upgrade_empty_db_matches_models(tmp_path):
    db_path = tmp_path / "empty.db"
    result = _run(db_path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    import models
    assert set(models.Base.metadata.tables) <= _tables(db_path)
    check = _run(db_path, "check")                       # 모델과 마이그레이션이 어긋나면 실패
    assert check.returncode == 0, check.stdout + check.stderr


def test_upgrade_existing_create_all_db(tmp_path):
    db_path = tmp_path / "existing.db"
    made = _run(db_path, code="import db; db.create_tables()")
    assert made.returncode == 0, made.stderr
    result = _run(db_path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert "alembic_version" in _tables(db_path)
    current = _run(db_path, "current")
    assert "0003" in current.stdout


def test_downgrade_to_base(tmp_path):
    db_path = tmp_path / "down.db"
    assert _run(db_path, "upgrade", "head").returncode == 0
    result = _run(db_path, "downgrade", "base")
    assert result.returncode == 0, result.stderr
    assert _tables(db_path) <= {"alembic_version"}
