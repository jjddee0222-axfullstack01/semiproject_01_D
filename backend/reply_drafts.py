"""
PIN POINT REVIEW - 리뷰 답글 초안 (US-16, CS챗봇 화면)

부정 리뷰는 이슈 유형별 사과 답글, 중립 리뷰는 감사 + 개선 약속 답글, 긍정 리뷰는 감사 답글 초안을 만듭니다.

지금은 템플릿으로 초안을 만듭니다 (llm_model = "template-v1").
LLM API 를 연결할 때는 generate_reply_draft() 안에서 API 를 호출하고,
돌려주는 모델 이름(DRAFT_MODEL)만 바꾸면 나머지 API·DB 저장은 그대로 동작합니다.
"""
try:
    from .models import IssueType, Polarity, Review
except ImportError:
    from models import IssueType, Polarity, Review

DRAFT_MODEL = "template-v1"

_BODY = {
    IssueType.DELIVERY: "배송 과정에서 불편을 드려 진심으로 죄송합니다. 택배사와 배송 과정을 바로 확인하고, "
                        "같은 일이 반복되지 않도록 배송 관리를 강화하겠습니다.",
    IssueType.PACKAGING: "포장 상태로 불쾌함을 드려 정말 죄송합니다. 상품이 안전하게 도착하도록 "
                         "포장 방식을 다시 점검하겠습니다.",
    IssueType.PRODUCT: "기대에 미치지 못하는 상품을 받으셔서 진심으로 사과드립니다. "
                       "말씀해 주신 내용을 품질 담당 부서에 바로 전달해 개선하겠습니다.",
    IssueType.ETC: "이용에 불편을 드려 진심으로 죄송합니다. 남겨 주신 의견을 꼼꼼히 확인해 개선하겠습니다.",
}


_THANKS = "소중한 리뷰 남겨 주셔서 진심으로 감사합니다. 앞으로도 만족하실 수 있도록 좋은 상품과 서비스로 보답하겠습니다."
_NEUTRAL = ("솔직한 리뷰 남겨 주셔서 감사합니다. 아쉬우셨던 점은 꼼꼼히 확인해 더 만족하실 수 있도록 개선하겠습니다.\n"
            "불편한 점이 있으시면 고객센터나 1:1 문의로 편하게 말씀해 주세요.")


def _masked(review: Review) -> str:
    name = review.reviewer_name or "고객"
    return name[0] + "*" * (len(name) - 1) if len(name) > 1 else name


def generate_reply_draft(review: Review, mall_name: str) -> tuple[str, str]:
    """(초안 본문, 사용한 모델 이름) — 긍정: 감사 답글 / 중립: 감사 + 개선 약속 / 부정: 사과 답글"""
    if review.analysis and review.analysis.sentiment == Polarity.POS:
        return f"안녕하세요, {_masked(review)} 고객님. {mall_name}입니다.\n{_THANKS}", DRAFT_MODEL
    if review.analysis and review.analysis.sentiment == Polarity.NEU:
        return f"안녕하세요, {_masked(review)} 고객님. {mall_name}입니다.\n{_NEUTRAL}\n감사합니다.", DRAFT_MODEL

    issue = review.analysis.issue_type if review.analysis and review.analysis.issue_type else IssueType.ETC
    masked = _masked(review)
    follow_up = ("교환 또는 환불을 원하시면 고객센터나 1:1 문의로 연락 주시면 빠르게 도와드리겠습니다."
                 if review.rating <= 2 else "더 좋은 상품과 서비스로 보답하겠습니다.")
    draft = f"안녕하세요, {masked} 고객님. {mall_name}입니다.\n{_BODY[issue]}\n{follow_up}\n감사합니다."
    return draft, DRAFT_MODEL
