"""8일차 Agent Task: CSV 업로드 입력 검증 개선 + 상태 확인 API (docs/11_final_report.md 부록 A, Task T-8-1)

완료조건
  1) 평점은 1~5 정수만 (4.5 처럼 소수점이 있으면 오류 행, 예전에는 4 로 잘라 저장)
  2) 작성일이 오늘 이후(미래)면 오류 행
  3) 상품명 255자·리뷰 본문 65,535바이트 초과는 잘라 저장하지 않고 오류 행
  4) 테스트 추가, 기존 URL·DB 구조 변경 없음
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

import models as m
from pipeline import PRODUCT_NAME_MAX, REVIEW_CONTENT_MAX_BYTES, _parse_rating
from tests.conftest import API

pytestmark = pytest.mark.pages


def upload(page, text: str):
    return page.post("/products/upload", files={"file": ("reviews.csv", text.encode("utf-8"), "text/csv")})


@pytest.mark.parametrize("value, expected", [("5", 5), ("5.0", 5), (" 3 ", 3), ("4.5", None), ("5.9", None),
                                             ("0", None), ("6", None), ("abc", None), ("", None)])
def test_rating_must_be_integer(value, expected):
    assert _parse_rating(value) == expected


def test_upload_rejects_bad_rows(page, session):
    future = (date.today() + timedelta(days=1)).isoformat()
    long_name = "가" * (PRODUCT_NAME_MAX + 1)
    long_body = "가" * (REVIEW_CONTENT_MAX_BYTES // 3 + 1)            # 한글 1자 = UTF-8 3바이트
    csv_text = ("상품명,평점,리뷰내용,작성일\n"
                "검증상품,5,정상 리뷰,2026-10-01\n"
                "검증상품,4.5,소수 평점,2026-10-01\n"
                f"검증상품,4,미래 날짜,{future}\n"
                f"{long_name},4,긴 상품명,2026-10-01\n"
                f"검증상품,4,{long_body},2026-10-01\n")
    r = upload(page, csv_text)
    assert "리뷰 1건 추가, 오류 4건 건너뜀" in r.text
    for text in ("3행(평점은 1~5 정수)", "4행(작성일이 미래)", f"5행(상품명 {PRODUCT_NAME_MAX}자 초과)", "6행(리뷰내용이 너무 김)"):
        assert text in r.text, text
    assert session.scalar(select(func.count()).select_from(m.Review).where(m.Review.content_raw == "소수 평점")) == 0
    assert session.scalar(select(func.count()).select_from(m.Product).where(func.length(m.Product.name) > PRODUCT_NAME_MAX)) == 0


def test_today_is_allowed(page):
    r = upload(page, f"상품명,평점,리뷰내용,작성일\n검증상품,5.0,오늘 리뷰,{date.today().isoformat()}\n")
    assert "리뷰 1건 추가" in r.text and "건너뜀" not in r.text


# ── 상태 확인 API (4일차 검증 기준 'GET → JSON 응답', 10일차 배포 후 서비스 확인)
def test_health_without_login(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok", "model_version": "rule-v2"}


def test_health_reports_db_error(client, monkeypatch):
    from sqlalchemy.orm import Session

    def broken(*_args, **_kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(Session, "execute", broken)
    r = client.get(f"{API}/health")
    assert r.status_code == 503 and r.json()["database"] == "error"
