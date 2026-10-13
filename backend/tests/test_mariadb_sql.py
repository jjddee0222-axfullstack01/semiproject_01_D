"""MariaDB 호환성: 서버 없이 MariaDB 문법으로 DDL·주요 쿼리를 만들어 봄"""
import pytest
from sqlalchemy import create_mock_engine, func, select
from sqlalchemy.dialects.mysql import mariadb

import models as m

pytestmark = pytest.mark.unit
DIALECT = mariadb.MariaDBDialect()


def _ddl():
    out = []
    engine = create_mock_engine("mariadb+pymysql://", lambda sql, *a, **k: out.append(str(sql.compile(dialect=engine.dialect))))
    m.Base.metadata.create_all(engine, checkfirst=False)
    return [s for s in out if s.lstrip().startswith("CREATE TABLE")]


def test_all_tables_innodb_utf8mb4():
    tables = _ddl()
    assert len(tables) == len(m.Base.metadata.tables) == 15
    for ddl in tables:
        assert "ENGINE=InnoDB" in ddl and "CHARSET=utf8mb4" in ddl, ddl[:80]


def test_erd_types():
    ddl = "\n".join(_ddl())
    for fragment in ("id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT", "business_number CHAR(10)",
                     "session_token_hash CHAR(64)", "mall_platform ENUM('NAVER','COUPANG','OWN','ETC')",
                     "status ENUM('VISIBLE','BLINDED')", "rating TINYINT UNSIGNED"):
        assert fragment in ddl, fragment


def test_monthly_group_uses_date_format():
    month = func.date_format(m.Review.reviewed_at, "%Y-%m")
    sql = str(select(month, func.count(m.Review.id)).group_by(month).compile(dialect=DIALECT))
    assert "date_format(reviews.reviewed_at" in sql.lower()
