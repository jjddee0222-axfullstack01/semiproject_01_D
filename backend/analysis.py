"""
PIN POINT REVIEW - 리뷰 분석 (규칙 기반, model_version = "rule-v1")

ERD의 REVIEW_ANALYSIS 컬럼을 채운다.
  sentiment (POS/NEG/NEU) · sentiment_score · severity (0~3) · issue_type (PRODUCT/DELIVERY/PACKAGING/ETC)

추후 감성 모델·LLM으로 바꿀 때는 analyze_review() 만 교체하고 MODEL_VERSION 을 올리면
model_version 으로 재분석 대상을 구분할 수 있다 (06_architecture 7장-6).
"""
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

try:
    from .models import IssueType, Polarity
except ImportError:
    from models import IssueType, Polarity

MODEL_VERSION = "rule-v1"

# severity 가 이 값 이상이면 '위험 리뷰' (대시보드 상단 노출 대상)
RISK_SEVERITY = 2

# 회원가입 시 셀러의 risk_keywords 에 기본으로 넣어 주는 위험 키워드 (word, weight)
DEFAULT_RISK_KEYWORDS = [
    ("환불", 2), ("반품", 1), ("교환", 1), ("불량", 2), ("파손", 2), ("누락", 2), ("최악", 2),
    ("곰팡이", 3), ("벌레", 3), ("이물질", 3), ("다쳤", 3), ("부작용", 3),
    ("사기", 3), ("신고", 3), ("고소", 3), ("소비자원", 3), ("짝퉁", 3), ("가품", 3),
]

# '파손 없이' 처럼 위험 단어가 부정형으로 쓰인 표현은 제외
NEGATED_PHRASES = ["파손 없이", "파손없이", "불량 없이", "불량없이", "누락 없이", "누락없이"]

# 리뷰에서 자주 언급되는 항목 → 이슈 유형
ASPECTS = {
    "배송": (["배송", "도착"], IssueType.DELIVERY),
    "포장": (["포장", "패키지", "상자", "박스", "찌그러"], IssueType.PACKAGING),
    "품질": (["품질", "마감", "퀄리티", "고급", "상태", "불량"], IssueType.PRODUCT),
    "위생": (["벌레", "이물질", "곰팡이", "냄새"], IssueType.PRODUCT),
    "색상": (["색감", "색상", "컬러"], IssueType.PRODUCT),
    "크기": (["크기", "사이즈"], IssueType.PRODUCT),
    "구성품": (["구성품", "누락", "빠져"], IssueType.PRODUCT),
    "상품 설명": (["설명과", "다른 제품", "사진과"], IssueType.PRODUCT),
    "가격": (["가성비", "가격", "저렴", "비싸"], IssueType.ETC),
    "재구매·추천": (["재구매", "추천"], IssueType.ETC),
}


@dataclass
class AnalysisResult:
    sentiment: Polarity
    sentiment_score: float      # 0.0(매우 부정) ~ 1.0(매우 긍정)
    severity: int               # 0~3
    issue_type: Optional[IssueType]


def _strip_negations(text: str) -> str:
    for phrase in NEGATED_PHRASES:
        text = text.replace(phrase, "")
    return text


def risk_weight(content: str, risk_keywords: Iterable[tuple[str, int]]) -> int:
    """리뷰에 포함된 위험 키워드 가중치 합"""
    text = _strip_negations(content)
    return sum(weight for word, weight in risk_keywords if word and word in text)


def aspects_in(content: str) -> list[str]:
    return [name for name, (words, _) in ASPECTS.items() if any(w in content for w in words)]


def analyze_review(content: str, rating: int, risk_keywords: Iterable[tuple[str, int]]) -> AnalysisResult:
    """리뷰 1건 분석

    severity  3: 위험 키워드 가중치 합 ≥ 3, 또는 (평점 ≤ 2 이면서 위험 키워드 포함)
              2: 평점 ≤ 2, 또는 위험 키워드 포함
              1: 평점 3 (아쉬움)
              0: 그 외
    sentiment : 평점 ≥ 4 이고 위험(severity ≥ 2)이 아니면 POS, 그 외 NEG
                (NEU 는 감성 모델 도입 시 사용)
    """
    weight = risk_weight(content, risk_keywords)
    if weight >= 3 or (rating <= 2 and weight > 0):
        severity = 3
    elif rating <= 2 or weight > 0:
        severity = 2
    elif rating == 3:
        severity = 1
    else:
        severity = 0

    sentiment = Polarity.POS if rating >= 4 and severity < RISK_SEVERITY else Polarity.NEG

    issue_type = None
    if sentiment == Polarity.NEG:
        found = [ASPECTS[a][1] for a in aspects_in(content) if ASPECTS[a][1] != IssueType.ETC]
        issue_type = Counter(found).most_common(1)[0][0] if found else IssueType.ETC

    return AnalysisResult(sentiment=sentiment, sentiment_score=round((rating - 1) / 4, 2),
                          severity=severity, issue_type=issue_type)


# ──────────────────────────────────────────────
# 긍정 / 부정 리뷰 요약 (상품별 대시보드)
# ──────────────────────────────────────────────
def _top_aspects(contents: list[str], limit: int = 3) -> list[str]:
    counter = Counter(a for c in contents for a in aspects_in(c))
    return [a for a, _ in counter.most_common(limit)]


def _join(aspects: list[str]) -> str:
    return ", ".join(f"'{a}'" for a in aspects)


def summarize_reviews(reviews: list) -> tuple[str, str]:
    """Review(ORM) 목록 → (긍정 요약, 부정 요약). review.analysis 가 있는 리뷰만 사용"""
    positives = [r.content_raw for r in reviews if r.analysis and r.analysis.sentiment == Polarity.POS]
    negatives = [r.content_raw for r in reviews if r.analysis and r.analysis.sentiment == Polarity.NEG]

    if not positives:
        positive = "아직 긍정 리뷰가 없습니다."
    else:
        aspects = _top_aspects(positives)
        positive = (f"{_join(aspects)}에 대한 칭찬이 주를 이룹니다." if aspects
                    else "전반적으로 만족한다는 의견이 많습니다.")
        positive += f" (긍정 리뷰 {len(positives)}건 기준)"

    if not negatives:
        negative = "아직 부정 리뷰가 없습니다."
    else:
        aspects = _top_aspects(negatives)
        negative = (f"{_join(aspects)} 관련 개선 요구가 있습니다." if aspects
                    else "일부 아쉽다는 의견이 있습니다.")
        negative += f" (부정 리뷰 {len(negatives)}건 기준)"

    return positive, negative
