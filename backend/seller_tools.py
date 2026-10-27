"""
PIN POINT REVIEW - 셀러 도구 (v1.2): 분석 결과를 '행동'으로 옮기도록 돕는 계산 모음

  1) 개선 조치 효과   action_effect        조치일 전후 같은 기간(최대 30일)의 리뷰를 비교
  2) 상세페이지 보완   detail_tips          부정·중립 리뷰에서 '설명이 있었으면 막을 수 있던 불만' 모으기
  3) 별점·내용 불일치  mismatch_condition   4~5점인데 아쉬움·불만이 섞인 리뷰 (SQL 조건)
  4) 답글 응답 시간    response_stats       리뷰 등록(업로드) → 첫 답글까지 걸린 시간, 오래 방치된 위험 리뷰
  5) 베스트 리뷰       best_reviews         상세페이지·SNS 에 쓸 만한 긍정 리뷰
  6) 강점 요약        strengths            긍정 키워드 TOP + 소개 문구 재료

모두 규칙 기반이며 분석 결과(review_analysis)를 바꾸지 않으므로 MODEL_VERSION 과 무관합니다.
화면(main.py)·API(api_v1.py)·리포트(insights.py)가 같은 함수를 씁니다.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

try:
    from .analysis import ISSUE_LABELS, RISK_SEVERITY
    from .models import (IssueType, Keyword, Polarity, Product, ProductAction, Review, ReviewAnalysis,
                         ReviewKeyword, ReviewReply, visible_reviews)
    from .privacy import mask_pii
except ImportError:
    from analysis import ISSUE_LABELS, RISK_SEVERITY
    from models import (IssueType, Keyword, Polarity, Product, ProductAction, Review, ReviewAnalysis,
                        ReviewKeyword, ReviewReply, visible_reviews)
    from privacy import mask_pii


def _scope(seller_id: int, product_id: Optional[int] = None):
    stmt = visible_reviews().join(Review.product).where(Product.seller_id == seller_id)
    return stmt.where(Review.product_id == product_id) if product_id else stmt


# ──────────────────────────────────────────────
# 1) 개선 조치 효과
# ──────────────────────────────────────────────
ACTION_WINDOW_DAYS = 30
ACTION_MIN_REVIEWS = 3          # 조치 후 리뷰가 이보다 적으면 '판단하기 이름'
ACTION_TITLE_MAX = 200


def _window_stats(reviews: list[Review], issue: Optional[IssueType]) -> dict:
    n = len(reviews)
    analyzed = [r for r in reviews if r.analysis]
    neg = [r for r in analyzed if r.analysis.sentiment == Polarity.NEG]
    target = [r for r in neg if issue is None or (r.analysis.issue_type or IssueType.ETC) == issue]
    return {"count": n,
            "avg_rating": round(sum(r.rating for r in reviews) / n, 2) if n else None,
            "negative_ratio": round(len(neg) / n * 100, 1) if n else None,
            "target": len(target),
            "target_ratio": round(len(target) / n * 100, 1) if n else None}


def action_effect(db: Session, action: ProductAction, *, today: Optional[date] = None) -> dict:
    """조치일 전 N일 vs 조치일부터 N일 (N = 30, 아직 30일이 안 지났으면 지난 날만큼 양쪽을 같게)"""
    today = today or date.today()
    elapsed = (today - action.action_date).days + 1
    days = max(1, min(ACTION_WINDOW_DAYS, elapsed))
    before_start = action.action_date - timedelta(days=days)
    after_end = action.action_date + timedelta(days=days - 1)
    reviews = db.scalars(
        visible_reviews().where(Review.product_id == action.product_id,
                                Review.reviewed_at >= before_start, Review.reviewed_at <= after_end)
        .options(selectinload(Review.analysis))
    ).all()
    before = _window_stats([r for r in reviews if r.reviewed_at < action.action_date], action.issue_type)
    after = _window_stats([r for r in reviews if r.reviewed_at >= action.action_date], action.issue_type)
    label = ISSUE_LABELS[action.issue_type] if action.issue_type else "전체 부정"

    if action.action_date > today:
        verdict, tone = "예정된 조치입니다. 조치일 이후 리뷰가 쌓이면 비교합니다.", "wait"
    elif after["count"] < ACTION_MIN_REVIEWS:
        verdict, tone = f"조치 후 리뷰가 {after['count']}건이라 아직 판단하기 이릅니다 ({ACTION_MIN_REVIEWS}건 이상 필요).", "wait"
    elif before["count"] == 0:
        verdict, tone = "조치 전 리뷰가 없어 비교할 수 없습니다.", "wait"
    else:
        diff = after["target_ratio"] - before["target_ratio"]
        if diff <= -5:
            verdict, tone = f"'{label}' 리뷰 비율이 {before['target_ratio']}% → {after['target_ratio']}% 로 줄었습니다. 효과가 있어 보입니다.", "good"
        elif diff >= 5:
            verdict, tone = f"'{label}' 리뷰 비율이 {before['target_ratio']}% → {after['target_ratio']}% 로 오히려 늘었습니다.", "bad"
        else:
            verdict, tone = f"'{label}' 리뷰 비율에 큰 변화가 없습니다 ({before['target_ratio']}% → {after['target_ratio']}%).", "same"
    return {"days": days, "before": before, "after": after, "target_label": label,
            "verdict": verdict, "tone": tone}


def product_actions(db: Session, product_id: int) -> list[ProductAction]:
    return db.scalars(select(ProductAction).where(ProductAction.product_id == product_id)
                      .order_by(ProductAction.action_date.desc(), ProductAction.id.desc())).all()


def action_problem(title: str, action_date: Optional[date], today: Optional[date] = None) -> Optional[str]:
    today = today or date.today()
    if not title:
        return "조치 내용을 입력해 주세요."
    if len(title) > ACTION_TITLE_MAX:
        return f"조치 내용은 {ACTION_TITLE_MAX}자 이하로 입력해 주세요."
    if action_date is None:
        return "조치일을 YYYY-MM-DD 형식으로 입력해 주세요."
    if action_date > today + timedelta(days=365) or action_date < today - timedelta(days=3650):
        return "조치일이 너무 멀리 떨어져 있습니다."
    return None


# ──────────────────────────────────────────────
# 2) 상세페이지 보완 포인트
# ──────────────────────────────────────────────
DETAIL_TOPICS = [
    # (항목, 찾을 단어, 상세페이지에 추가할 내용)
    ("사이즈", ["사이즈", "크기", "작아", "작네", "커요", "크네", "커서", "핏", "길이", "치수"],
     "실측 사이즈표(가로·세로·높이 cm)와 사람·물건과 함께 찍은 비교 사진을 추가하세요."),
    ("색상", ["색상", "색감", "색이", "컬러", "어두", "밝아", "사진이랑", "사진과"],
     "자연광에서 찍은 실물 사진과 '모니터에 따라 색이 다를 수 있음' 안내를 추가하세요."),
    ("구성품", ["구성품", "구성", "누락", "빠져", "개수", "부품", "들어있"],
     "구성품 목록과 전체 구성 사진(펼쳐 놓은 사진)을 추가하세요."),
    ("사용법", ["사용법", "설명서", "조립", "사용 방법", "쓰는 법", "어떻게 쓰", "작동"],
     "사용·조립 순서를 사진이나 짧은 영상으로 단계별로 보여 주세요."),
    ("소재·두께", ["소재", "재질", "원단", "얇", "두께", "비침", "촉감"],
     "소재 구성(%)과 두께·비침 정도를 표로 안내하세요."),
    ("냄새", ["냄새", "향이", "향은", "악취"],
     "첫 개봉 시 냄새 여부와 없애는 방법(환기 시간 등)을 안내하세요."),
    ("무게", ["무거", "무게", "가벼"],
     "제품 무게(g)를 명시하고 들고 있는 사진을 추가하세요."),
    ("배송 기간", ["늦게", "오래 걸", "언제 와", "배송이 느"],
     "주문 후 출고·도착 예상일과 주문 마감 시간을 상단에 안내하세요."),
]
DETAIL_TIPS_LIMIT = 5


@dataclass
class DetailTip:
    topic: str
    count: int
    suggestion: str
    examples: list[str] = field(default_factory=list)


def detail_tips(db: Session, seller_id: int, product_id: Optional[int] = None,
                limit: int = DETAIL_TIPS_LIMIT) -> list[DetailTip]:
    """부정·중립 리뷰에서 항목별 언급 수 (많은 순). 예시는 개인정보를 가린 앞부분 2개"""
    reviews = db.scalars(
        _scope(seller_id, product_id).join(Review.analysis)
        .where(ReviewAnalysis.sentiment.in_([Polarity.NEG, Polarity.NEU]))
        .order_by(Review.reviewed_at.desc(), Review.id.desc())
    ).all()
    tips = []
    for topic, words, suggestion in DETAIL_TOPICS:
        hits = [r for r in reviews if any(w in r.content_raw for w in words)]
        if hits:
            examples = [_snippet(r.content_raw) for r in hits[:2]]
            tips.append(DetailTip(topic, len(hits), suggestion, examples))
    tips.sort(key=lambda t: (-t.count, t.topic))
    return tips[:limit]


def _snippet(text: str, length: int = 60) -> str:
    text = mask_pii(text.replace("\n", " "))
    return text if len(text) <= length else text[:length] + "…"


# ──────────────────────────────────────────────
# 3) 별점·내용 불일치 (4~5점인데 아쉬움·불만)
# ──────────────────────────────────────────────
MISMATCH_CUES = ["근데", "그런데", "하지만", "그러나", "다만", "아쉽", "아쉬", "별로", "불편", "실망", "불만",
                 "그닥", "글쎄"]


def mismatch_condition():
    """SQL 조건: 평점 4점 이상 + (부정으로 분석됨 또는 아쉬움 표현 포함). ReviewAnalysis 가 조인돼 있어야 함"""
    cue = or_(*(Review.content_raw.contains(w, autoescape=True) for w in MISMATCH_CUES))
    return and_(Review.rating >= 4, or_(ReviewAnalysis.sentiment == Polarity.NEG, cue))


def mismatch_count(db: Session, seller_id: int, product_id: Optional[int] = None) -> int:
    return db.scalar(_scope(seller_id, product_id).outerjoin(Review.analysis).where(mismatch_condition())
                     .with_only_columns(func.count(Review.id))) or 0


# ──────────────────────────────────────────────
# 4) 답글 응답 시간
#    시작 시각 = 리뷰가 서비스에 들어온 시각(created_at). 예전 리뷰를 한꺼번에 올려도 응답 시간이 부풀지 않음
# ──────────────────────────────────────────────
OVERDUE_DAYS = 3


def _hours_text(hours: Optional[float]) -> str:
    if hours is None:
        return "-"
    if hours < 1:
        return "1시간 이내"
    if hours < 48:
        return f"{hours:.0f}시간"
    return f"{hours / 24:.1f}일"


def response_stats(db: Session, seller_id: int, *, since: Optional[date] = None,
                   until: Optional[date] = None, now: Optional[datetime] = None) -> dict:
    """{avg_hours, avg_text, replied, within_day_ratio, overdue_risky}. since/until 은 리뷰 작성일 기준 범위

    created_at 은 DB 기본값(서버 시각)으로 저장되므로 '지금'도 DB 시각으로 비교 (SQLite=UTC, MariaDB=서버 시간대)
    """
    if now is None:
        now = db.scalar(select(func.now()))
        if isinstance(now, str):                     # 일부 드라이버는 문자열로 돌려줌
            now = datetime.fromisoformat(now)
    first_reply = (select(ReviewReply.review_id, func.min(ReviewReply.created_at).label("first_at"))
                   .group_by(ReviewReply.review_id).subquery())
    stmt = (_scope(seller_id).join(first_reply, first_reply.c.review_id == Review.id)
            .with_only_columns(Review.created_at, first_reply.c.first_at))
    if since:
        stmt = stmt.where(Review.reviewed_at >= since)
    if until:
        stmt = stmt.where(Review.reviewed_at <= until)
    hours = [max((first - created).total_seconds() / 3600, 0) for created, first in db.execute(stmt).all()]
    avg = sum(hours) / len(hours) if hours else None

    overdue = db.scalar(
        _scope(seller_id).join(Review.analysis)
        .where(ReviewAnalysis.severity >= RISK_SEVERITY, ~Review.replies.any(),
               Review.created_at <= now - timedelta(days=OVERDUE_DAYS))
        .with_only_columns(func.count(Review.id))) or 0
    return {"avg_hours": round(avg, 1) if avg is not None else None, "avg_text": _hours_text(avg),
            "replied": len(hours),
            "within_day_ratio": round(sum(1 for h in hours if h <= 24) / len(hours) * 100, 1) if hours else None,
            "overdue_risky": overdue, "overdue_days": OVERDUE_DAYS}


# ──────────────────────────────────────────────
# 5) 베스트 리뷰 / 6) 강점 요약
# ──────────────────────────────────────────────
BEST_MIN_LENGTH = 15


def best_reviews(db: Session, seller_id: int, product_id: Optional[int] = None, limit: int = 10) -> list[dict]:
    """5점·긍정·위험 아님·아쉬움 표현 없음 → (긍정 키워드 수, 길이(최대 200자), 최신) 순"""
    rows = db.scalars(
        _scope(seller_id, product_id).join(Review.analysis)
        .where(Review.rating == 5, ReviewAnalysis.sentiment == Polarity.POS,
               ReviewAnalysis.severity < RISK_SEVERITY)
        .options(selectinload(Review.product),
                 selectinload(Review.keyword_links).selectinload(ReviewKeyword.keyword))
    ).all()
    picked = []
    for r in rows:
        text = r.content_raw.strip()
        if len(text) < BEST_MIN_LENGTH or any(c in text for c in MISMATCH_CUES):
            continue
        pos_words = [l.keyword.word for l in r.keyword_links if l.keyword.polarity == Polarity.POS]
        score = len(pos_words) * 50 + min(len(text), 200)
        picked.append((score, r.reviewed_at, r.id, r, pos_words))
    picked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [{"id": r.id, "product_id": r.product_id, "product_name": r.product.name,
             "reviewer": _masked_name(r.reviewer_name), "reviewed_at": r.reviewed_at,
             "content": mask_pii(r.content_raw.strip()), "keywords": words}
            for _, _, _, r, words in picked[:limit]]


def _masked_name(name: Optional[str]) -> str:
    name = name or "고객"
    return name[0] + "*" * (len(name) - 1) if len(name) > 1 else name


# 긍정 키워드('○○ 만족') → 소개 문구에 쓸 짧은 표현
STRENGTH_PHRASES = {
    "배송": "빠르고 안전한 배송", "포장": "꼼꼼한 포장", "품질": "만족스러운 품질·마감",
    "위생": "깔끔한 위생 상태", "색상": "사진 그대로의 색감", "크기": "딱 맞는 크기",
    "구성품": "알찬 구성", "상품 설명": "설명과 같은 상품", "가격": "뛰어난 가성비",
    "재구매·추천": "재구매·추천이 많은 상품",
}


def strengths(db: Session, seller_id: int, product_id: Optional[int] = None, limit: int = 5) -> dict:
    """{keywords: [{word, phrase, count}], review_count, avg_rating, sentences: [소개 문구 예시]}"""
    scope = _scope(seller_id, product_id)
    total, avg = db.execute(scope.with_only_columns(func.count(Review.id), func.avg(Review.rating))).one()
    rows = db.execute(
        scope.join(Review.keyword_links).join(ReviewKeyword.keyword)
        .where(Keyword.polarity == Polarity.POS)
        .with_only_columns(Keyword.word, func.count(Review.id))
        .group_by(Keyword.id, Keyword.word)
        .order_by(func.count(Review.id).desc(), Keyword.word).limit(limit)
    ).all()
    keywords = []
    for word, count in rows:
        aspect = word.removesuffix(" 만족")
        keywords.append({"word": word, "phrase": STRENGTH_PHRASES.get(aspect, aspect), "count": count})

    sentences = []
    if keywords and total:
        phrases = [k["phrase"] for k in keywords[:2]]
        rating = f", 평균 ★{float(avg):.1f}" if avg is not None and float(avg) >= 4.0 else ""   # 낮은 평점은 문구에 넣지 않음
        sentences.append(f"구매 고객 리뷰 {total:,}건{rating}! 특히 {' · '.join(phrases)}을(를) 많이 칭찬해 주셨어요.")
        top = keywords[0]
        sentences.append(f"\"{top['phrase']}\" — 실제 리뷰 {top['count']:,}건에서 확인된 장점입니다.")
        if len(keywords) >= 3:
            sentences.append("고객이 말하는 이 상품의 장점: " + ", ".join(k["phrase"] for k in keywords[:3]))
    return {"keywords": keywords, "review_count": int(total or 0),
            "avg_rating": round(float(avg), 2) if avg is not None else None, "sentences": sentences}
