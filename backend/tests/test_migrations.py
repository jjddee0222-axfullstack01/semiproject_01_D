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
    env = {**os.environ, "DATABASE_URL": "sqlite:///" + db_path.as_posix()}
    cmd = [sys.executable, "-c", code] if code else [sys.executable, "-m", "alembic", *args]
    return subprocess.run(cmd, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)


def _tables(db_path):
    import sqlite3
    with sqlite3.connect(db_path) as con:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


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
