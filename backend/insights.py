"""
PIN POINT REVIEW - 인사이트 (v1.1): 부정 키워드 급증 감지 · 주간/월간 리포트

급증 기준 (SURGE_*)
  - 대상: 부정(NEG) 키워드, 블라인드 제외(VISIBLE) 리뷰, 로그인한 셀러의 상품
  - 최근 7일(오늘 포함) 등장 리뷰 수 vs 그 전 7일
  - 최근 3건 이상 이면서 (이전 0건 또는 2배 이상) → 급증
화면(대시보드 카드)과 API(GET /api/v1/stats/keyword-surges)가 같은 함수를 사용

주간/월간 리포트 (period_report → /reports 화면, 브라우저 인쇄로 PDF 저장)
  - 주간 = 최근 7일, 월간 = 최근 30일 (오늘 포함), 바로 앞 같은 길이 기간과 비교
  - 블라인드 제외(VISIBLE) 리뷰만, 요약 문장은 분석 화면과 같은 규칙(shop_report)
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session, selectinload

try:
    from .analysis import ISSUE_LABELS, RISK_SEVERITY, shop_report
    from .models import IssueType, Keyword, Polarity, Product, Review, ReviewKeyword, visible_reviews
    from .seller_tools import response_stats
except ImportError:
    from analysis import ISSUE_LABELS, RISK_SEVERITY, shop_report
    from models import IssueType, Keyword, Polarity, Product, Review, ReviewKeyword, visible_reviews
    from seller_tools import response_stats

SURGE_DAYS = 7
SURGE_MIN_COUNT = 3
SURGE_RATIO = 2.0


@dataclass
class KeywordSurge:
    word: str
    current: int            # 최근 기간 등장 리뷰 수
    previous: int           # 이전 기간 등장 리뷰 수
    ratio: Optional[float]  # current / previous (이전 0건이면 None = 새로 등장)


def keyword_surges(db: Session, seller_id: int, *, days: int = SURGE_DAYS, today: Optional[date] = None,
                   limit: int = 5) -> list[KeywordSurge]:
    """부정 키워드 급증 목록 (증가폭 큰 순)"""
    today = today or date.today()
    current_start = today - timedelta(days=days - 1)
    previous_start = current_start - timedelta(days=days)
    in_current = func.sum(case((Review.reviewed_at >= current_start, 1), else_=0))
    in_previous = func.sum(case((Review.reviewed_at < current_start, 1), else_=0))
    rows = db.execute(
        visible_reviews().join(Review.product).join(Review.keyword_links).join(ReviewKeyword.keyword)
        .where(Product.seller_id == seller_id, Keyword.polarity == Polarity.NEG,
               Review.reviewed_at >= previous_start, Review.reviewed_at <= today)
        .with_only_columns(Keyword.word, in_current, in_previous)
        .group_by(Keyword.id, Keyword.word)
    ).all()

    surges = []
    for word, current, previous in rows:
        current, previous = int(current or 0), int(previous or 0)
        if current < SURGE_MIN_COUNT:
            continue
        if previous and current / previous < SURGE_RATIO:
            continue
        surges.append(KeywordSurge(word, current, previous, round(current / previous, 1) if previous else None))
    surges.sort(key=lambda s: (s.current - s.previous, s.current, s.word), reverse=True)
    return surges[:limit]


# ──────────────────────────────────────────────
# 주간 / 월간 리포트
# ──────────────────────────────────────────────
REPORT_PERIODS = {"week": ("주간", 7), "month": ("월간", 30)}
REPORT_TOP = 5


def _kpis(reviews: list[Review]) -> dict:
    n = len(reviews)
    analyzed = [r for r in reviews if r.analysis]
    neg = sum(1 for r in analyzed if r.analysis.sentiment == Polarity.NEG)
    risky = sum(1 for r in analyzed if r.analysis.severity >= RISK_SEVERITY)
    replied = sum(1 for r in reviews if r.replies)
    return {"count": n,
            "avg_rating": round(sum(r.rating for r in reviews) / n, 2) if n else None,
            "negative_ratio": round(neg / n * 100, 1) if n else None,
            "risky": risky,
            "reply_rate": round(replied / n * 100, 1) if n else None}


def _delta(now, before):
    if now is None or before is None:
        return None
    return round(now - before, 2)


def period_report(db: Session, seller_id: int, period: str = "week", *, today: Optional[date] = None) -> dict:
    """리포트 화면에 필요한 값 모음 (period: week | month)"""
    label, days = REPORT_PERIODS.get(period, REPORT_PERIODS["week"])
    period = period if period in REPORT_PERIODS else "week"
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    prev_start, prev_end = start - timedelta(days=days), start - timedelta(days=1)

    reviews = db.scalars(
        visible_reviews().join(Review.product)
        .where(Product.seller_id == seller_id, Review.reviewed_at >= prev_start, Review.reviewed_at <= today)
        .options(selectinload(Review.analysis), selectinload(Review.product), selectinload(Review.replies),
                 selectinload(Review.keyword_links).selectinload(ReviewKeyword.keyword))
        .order_by(Review.reviewed_at.desc(), Review.id.desc())
    ).all()
    current = [r for r in reviews if r.reviewed_at >= start]
    previous = [r for r in reviews if r.reviewed_at < start]

    now_k, prev_k = _kpis(current), _kpis(previous)
    kpis = [
        {"label": "리뷰 수", "value": now_k["count"], "unit": "건", "delta": now_k["count"] - prev_k["count"],
         "good_when": "up"},
        {"label": "평균 평점", "value": now_k["avg_rating"], "unit": "점",
         "delta": _delta(now_k["avg_rating"], prev_k["avg_rating"]), "good_when": "up"},
        {"label": "부정 리뷰 비율", "value": now_k["negative_ratio"], "unit": "%",
         "delta": _delta(now_k["negative_ratio"], prev_k["negative_ratio"]), "good_when": "down"},
        {"label": "위험 리뷰", "value": now_k["risky"], "unit": "건", "delta": now_k["risky"] - prev_k["risky"],
         "good_when": "down"},
        {"label": "답글 처리율", "value": now_k["reply_rate"], "unit": "%",
         "delta": _delta(now_k["reply_rate"], prev_k["reply_rate"]), "good_when": "up"},
    ]
    # v1.2 답글 응답 시간 (리뷰 등록 → 첫 답글, 작성일이 기간 안인 리뷰 기준)
    resp_now = response_stats(db, seller_id, since=start, until=today)
    resp_prev = response_stats(db, seller_id, since=prev_start, until=prev_end)
    kpis.append({"label": "평균 답글 시간", "value": resp_now["avg_hours"], "unit": "시간",
                 "delta": _delta(resp_now["avg_hours"], resp_prev["avg_hours"]), "good_when": "down"})

    analyzed = [r for r in current if r.analysis]
    sentiment_counts = Counter(r.analysis.sentiment for r in analyzed)
    total = len(analyzed) or 1
    sentiments = [{"key": p.value, "label": lbl, "count": sentiment_counts.get(p, 0),
                   "ratio": round(sentiment_counts.get(p, 0) / total * 100, 1)}
                  for p, lbl in ((Polarity.POS, "긍정"), (Polarity.NEU, "중립"), (Polarity.NEG, "부정"))]

    negatives = [r for r in analyzed if r.analysis.sentiment == Polarity.NEG]
    issue_counter = Counter(r.analysis.issue_type or IssueType.ETC for r in negatives)
    issue_max = max(issue_counter.values(), default=0) or 1
    issues = [{"label": ISSUE_LABELS[i], "count": n, "width": round(n / issue_max * 100)}
              for i, n in issue_counter.most_common()]

    def top_words(polarity):
        counter = Counter(link.keyword.word for r in current for link in r.keyword_links
                          if link.keyword.polarity == polarity)
        return counter.most_common(REPORT_TOP)

    by_product: dict[int, dict] = {}
    for r in reviews:
        row = by_product.setdefault(r.product_id, {"name": r.product.name, "count": 0, "prev_count": 0,
                                                   "rating_sum": 0, "negative": 0, "risky": 0})
        if r.reviewed_at < start:
            row["prev_count"] += 1
            continue
        row["count"] += 1
        row["rating_sum"] += r.rating
        if r.analysis and r.analysis.sentiment == Polarity.NEG:
            row["negative"] += 1
        if r.analysis and r.analysis.severity >= RISK_SEVERITY:
            row["risky"] += 1
    products = sorted(
        ({**row, "avg_rating": round(row["rating_sum"] / row["count"], 2) if row["count"] else None}
         for row in by_product.values() if row["count"] or row["prev_count"]),
        key=lambda x: (-x["risky"], -x["count"], x["name"]))

    risky_reviews = sorted((r for r in analyzed if r.analysis.severity >= RISK_SEVERITY),
                           key=lambda r: (-r.analysis.severity, -r.reviewed_at.toordinal(), -r.id))[:REPORT_TOP]

    return {
        "period": period, "label": label, "days": days,
        "start": start, "end": today, "prev_start": prev_start, "prev_end": prev_end,
        "kpis": kpis, "sentiments": sentiments, "issues": issues,
        "negative_keywords": top_words(Polarity.NEG), "positive_keywords": top_words(Polarity.POS),
        "surges": keyword_surges(db, seller_id, days=days, today=today),
        "products": products, "risky_reviews": risky_reviews,
        "summary": shop_report(current),
    }
