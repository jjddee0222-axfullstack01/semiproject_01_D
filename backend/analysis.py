"""
PIN POINT REVIEW - 리뷰 분석 (규칙 기반, model_version = "rule-v2")

ERD의 REVIEW_ANALYSIS 컬럼을 채운다.
  sentiment (POS/NEG/NEU) · sentiment_score · severity (0~3) · issue_type (PRODUCT/DELIVERY/PACKAGING/ETC)

추후 감성 모델·LLM으로 바꿀 때는 analyze_review() 만 교체하고 MODEL_VERSION 을 올리면
model_version 으로 재분석 대상을 구분할 수 있다 (06_architecture 7장-6).
"""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

try:
    from .models import IssueType, Polarity
except ImportError:
    from models import IssueType, Polarity

MODEL_VERSION = "rule-v2"     # v2: 위험 키워드 없는 3점 리뷰를 중립(NEU)으로 분류

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


# ──────────────────────────────────────────────
# 텍스트 클리닝 (US-10: 원문 content_raw 는 그대로 두고 정제본 content_clean 에 저장)
# ──────────────────────────────────────────────
_URL = re.compile(r"https?://\S+|www\.\S+")
_HTML = re.compile(r"<[^>]+>")
_ALLOWED = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ\s.,!?~%]")     # 한글·영문·숫자·기본 문장부호만 남김
_REPEAT = re.compile(r"([!?.~ㅋㅎㅠㅜ])\1{2,}")                  # !!!!, ㅋㅋㅋㅋ → 2개로
_SPACES = re.compile(r"\s+")


def clean_text(text: str) -> str:
    text = _HTML.sub(" ", text or "")
    text = _URL.sub(" ", text)
    text = _ALLOWED.sub(" ", text)
    text = _REPEAT.sub(r"\1\1", text)
    return _SPACES.sub(" ", text).strip()


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
    sentiment : POS  평점 ≥ 4 이고 위험(severity ≥ 2)이 아님
                NEU  평점 3 이고 위험 키워드가 없음 ('그럭저럭', '조금 아쉬움' 정도의 리뷰)
                NEG  그 외 (평점 1~2, 또는 위험 키워드가 들어간 리뷰)
    issue_type: 부정(NEG) 리뷰만 (상품/배송/포장/기타)
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

    if rating >= 4 and severity < RISK_SEVERITY:
        sentiment = Polarity.POS
    elif rating == 3 and weight == 0:
        sentiment = Polarity.NEU
    else:
        sentiment = Polarity.NEG

    issue_type = None
    if sentiment == Polarity.NEG:
        found = [ASPECTS[a][1] for a in aspects_in(content) if ASPECTS[a][1] != IssueType.ETC]
        issue_type = Counter(found).most_common(1)[0][0] if found else IssueType.ETC

    return AnalysisResult(sentiment=sentiment, sentiment_score=round((rating - 1) / 4, 2),
                          severity=severity, issue_type=issue_type)


# ──────────────────────────────────────────────
# 키워드 추출 (keywords / review_keywords → 키워드 TOP 10)
#   항목 + 감성: '배송 만족', '포장 불만' …  / 위험 키워드: '환불', '불량' … (부정)
#   같은 단어는 항상 같은 극성이 되도록 '만족'/'불만'을 붙인다 (keywords.word 는 UNIQUE)
# ──────────────────────────────────────────────
POSITIVE_ONLY_ASPECTS = {"재구매·추천"}     # '재구매·추천 불만' 같은 어색한 키워드는 만들지 않음


def extract_keywords(content: str, sentiment: Polarity,
                     risk_keywords: Iterable[tuple[str, int]]) -> list[tuple[str, Polarity, float]]:
    """리뷰 1건 → [(키워드, 극성, 점수)]. 점수는 리뷰 안에서의 중요도(0~1)

    중립(NEU) 리뷰는 '만족'/'불만' 어느 쪽도 아니므로 항목 키워드를 만들지 않음 (키워드 TOP 10 은 긍정·부정만)
    """
    result: dict[str, tuple[Polarity, float]] = {}
    if sentiment == Polarity.NEU:
        return []
    polarity = Polarity.POS if sentiment == Polarity.POS else Polarity.NEG
    suffix = "만족" if polarity == Polarity.POS else "불만"
    for aspect in aspects_in(content):
        if polarity == Polarity.NEG and aspect in POSITIVE_ONLY_ASPECTS:
            continue
        result[f"{aspect} {suffix}"] = (polarity, 0.5)

    text = _strip_negations(content)
    for word, weight in risk_keywords:
        if word and word in text:
            result[word] = (Polarity.NEG, round(min(weight, 3) / 3, 2))
    return [(w, pol, score) for w, (pol, score) in result.items()]


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


# ──────────────────────────────────────────────
# 쇼핑몰 분석 리포트 (analysis.html 의 'AI 분석 봇 리포트')
#   지금은 규칙 기반(rule-v2). LLM 을 붙일 때는 shop_report() 의 반환 형식만 유지하면
#   화면(템플릿)은 그대로 쓸 수 있다.
# ──────────────────────────────────────────────
ISSUE_LABELS = {
    IssueType.PRODUCT: "상품 품질",
    IssueType.DELIVERY: "배송",
    IssueType.PACKAGING: "포장",
    IssueType.ETC: "기타",
}

# 이슈 유형별 개선 방안
RECOMMENDATIONS = {
    IssueType.PRODUCT: "불만이 집중된 상품의 검수 기준을 강화하고, 상세 페이지의 색상·크기 설명을 실제와 맞게 보완하세요.",
    IssueType.DELIVERY: "출고 지연 구간을 확인하고, 배송 예정일 안내 문구를 상세 페이지와 주문 알림에 추가하세요.",
    IssueType.PACKAGING: "완충재·박스 규격을 점검하고 파손 다발 상품은 이중 포장을 적용하세요.",
    IssueType.ETC: "부정 리뷰에 빠르게 답글을 달아 고객 불만이 확산되지 않도록 관리하세요.",
}


def shop_report(reviews: list) -> dict:
    """Review(ORM, analysis 로드됨) 목록 → 쇼핑몰 전체 분석 리포트

    반환: {strengths, weaknesses, recommendations: [str], issue_counts: [(라벨, 건수)],
          positive_count, negative_count}
    """
    analyzed = [r for r in reviews if r.analysis]
    positives = [r.content_raw for r in analyzed if r.analysis.sentiment == Polarity.POS]
    negatives = [r for r in analyzed if r.analysis.sentiment == Polarity.NEG]

    pos_aspects = _top_aspects(positives)
    neg_aspects = _top_aspects([r.content_raw for r in negatives])
    issue_counter = Counter(r.analysis.issue_type or IssueType.ETC for r in negatives)

    if not analyzed:
        return {"strengths": "아직 분석된 리뷰가 없습니다.", "weaknesses": "", "recommendations": [],
                "issue_counts": [], "positive_count": 0, "negative_count": 0}

    strengths = (f"고객들은 {_join(pos_aspects)}을(를) 가장 많이 칭찬했습니다." if pos_aspects
                 else "뚜렷하게 칭찬이 몰린 항목은 아직 없습니다.")
    if negatives:
        top_issue, top_count = issue_counter.most_common(1)[0]
        weaknesses = (f"부정 리뷰 {len(negatives)}건 중 '{ISSUE_LABELS[top_issue]}' 문제가 {top_count}건으로 가장 많습니다."
                      + (f" 주로 {_join(neg_aspects)} 관련 내용입니다." if neg_aspects else ""))
        recommendations = [RECOMMENDATIONS[issue] for issue, _ in issue_counter.most_common(2)]
    else:
        weaknesses = "부정 리뷰가 없습니다."
        recommendations = ["현재 강점을 상세 페이지와 광고 문구에 적극적으로 활용하세요."]

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": recommendations,
        "issue_counts": [(ISSUE_LABELS[i], n) for i, n in issue_counter.most_common()],
        "positive_count": len(positives),
        "negative_count": len(negatives),
    }
