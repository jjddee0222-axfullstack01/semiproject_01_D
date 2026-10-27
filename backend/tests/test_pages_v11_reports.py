"""v1.1 주간/월간 리포트 (/reports) — 인쇄(PDF 저장)용 화면"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

import insights
import models as m

pytestmark = pytest.mark.pages


def test_reports_requires_login(client):
    r = client.get("/reports", follow_redirects=False)
    assert r.status_code in (302, 303) and "/login" in r.headers["location"]


def test_reports_week_default(page):
    r = page.get("/reports")
    assert r.status_code == 200
    text = r.text
    assert "피인포인트몰 주간 리뷰 리포트" in text and "window.print()" in text and "@media print" in text
    assert '/reports">리포트</a>' in text                       # 사이드바 메뉴
    for label in ("핵심 지표", "감성 분포", "부정 리뷰 이슈 유형", "키워드 TOP 5", "상품별 현황", "주의가 필요한 위험 리뷰"):
        assert label in text, label
    start = date.today() - timedelta(days=6)
    assert start.strftime("%Y.%m.%d") in text


def test_reports_month_and_bad_period(page):
    assert "월간 리뷰 리포트" in page.get("/reports?period=month").text
    assert "주간 리뷰 리포트" in page.get("/reports?period=year").text      # 모르는 값은 주간


def test_period_report_numbers(session):
    demo = session.scalar(select(m.User))
    week = insights.period_report(session, demo.id, "week")
    # 데모 리뷰: 1~6일 전 6건(오늘 기준 7일 안), 7~11일 전 5건
    kpi = {k["label"]: k for k in week["kpis"]}
    assert kpi["리뷰 수"]["value"] == 6 and kpi["리뷰 수"]["delta"] == 6 - 5
    assert sum(s["count"] for s in week["sentiments"]) == 6
    month = insights.period_report(session, demo.id, "month")
    assert {k["label"]: k for k in month["kpis"]}["리뷰 수"]["value"] == 11
    assert len(month["risky_reviews"]) == 3                    # 상품마다 위험 리뷰 1건
    assert month["risky_reviews"][0].analysis.severity >= month["risky_reviews"][-1].analysis.severity
    assert {p["name"] for p in month["products"]} == {p.name for p in session.scalars(select(m.Product))}


def test_reports_exclude_blinded_and_other_sellers(page, other_api, session, ids):
    page.post(f"/reviews/{ids['risky_a']}/blind", data={"reason": "욕설"})
    demo = session.scalar(select(m.User))
    month = insights.period_report(session, demo.id, "month")
    assert {k["label"]: k for k in month["kpis"]}["리뷰 수"]["value"] == 10
    assert "불량품이 왔어요" not in page.get("/reports?period=month").text
    text = other_api.get("/reports?period=month").text
    assert "이 기간에 들어온 리뷰가 없습니다" in text and "프리미엄 시그니처" not in text
