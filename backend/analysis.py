"""
PIN POINT REVIEW - 리뷰 분석 (위험 리뷰 감지 / 긍정·부정 분류 / 요약)

지금은 키워드 규칙 기반이며, 추후 AI 모델로 교체할 때
이 파일의 함수만 바꾸면 나머지 코드는 그대로 사용할 수 있다.
"""
from collections import Counter
from typing import Iterable

# ──────────────────────────────────────────────
# 위험 리뷰 감지
# ──────────────────────────────────────────────
RISK_KEYWORDS = [
    "환불", "사기", "신고", "고소", "최악", "불량", "파손", "누락",
    "곰팡이", "벌레", "다쳤", "부작용", "소비자원", "짝퉁", "가품",
]


def is_risky_review(content: str, rating: int) -> bool:
    """평점이 낮거나 위험 키워드가 포함되면 위험 리뷰로 판단"""
    if rating <= 2:
        return True
    # '파손 없이'처럼 부정형으로 쓰인 경우는 제외
    text = content.replace("파손 없이", "").replace("파손없이", "")
    return any(keyword in text for keyword in RISK_KEYWORDS)


# ──────────────────────────────────────────────
# 긍정 / 부정 분류
# ──────────────────────────────────────────────
def is_positive(review) -> bool:
    return review["rating"] >= 4 and not review["is_risky"]


def is_negative(review) -> bool:
    return review["rating"] <= 3 or bool(review["is_risky"])


# ──────────────────────────────────────────────
# 긍정 / 부정 리뷰 요약
# ──────────────────────────────────────────────
# 리뷰에서 자주 언급되는 항목과 그 항목을 가리키는 단어
ASPECTS = {
    "배송": ["배송", "도착"],
    "품질": ["품질", "마감", "퀄리티", "고급", "상태", "불량"],
    "포장": ["포장", "패키지", "상자", "박스"],
    "색상": ["색감", "색상", "컬러"],
    "가격": ["가성비", "가격", "저렴", "비싸"],
    "크기": ["크기", "사이즈"],
    "구성품": ["구성품", "누락", "빠져"],
    "상품 설명": ["설명과", "다른 제품", "사진과"],
    "재구매·추천": ["재구매", "추천"],
}


def _top_aspects(reviews: Iterable, limit: int = 3) -> list[str]:
    counter = Counter()
    for review in reviews:
        for aspect, words in ASPECTS.items():
            if any(word in review["content"] for word in words):
                counter[aspect] += 1
    return [aspect for aspect, _ in counter.most_common(limit)]


def _join(aspects: list[str]) -> str:
    return ", ".join(f"'{a}'" for a in aspects)


def summarize_reviews(reviews: list) -> tuple[str, str]:
    """(긍정 리뷰 요약, 부정 리뷰 요약) 문장을 만든다"""
    positives = [r for r in reviews if is_positive(r)]
    negatives = [r for r in reviews if is_negative(r)]

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
