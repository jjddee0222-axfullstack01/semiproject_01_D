"""
PIN POINT REVIEW - 부정 리뷰 사과 답글 초안 (US-16)

지금은 이슈 유형별 템플릿으로 초안을 만듭니다 (llm_model = "template-v1").
LLM API 를 연결할 때는 generate_reply_draft() 안에서 API 를 호출하고,
돌려주는 모델 이름(DRAFT_MODEL)만 바꾸면 나머지 API·DB 저장은 그대로 동작합니다.
"""
try:
    from .models import IssueType, Review
except ImportError:
    from models import IssueType, Review

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


def generate_reply_draft(review: Review, mall_name: str) -> tuple[str, str]:
    """(초안 본문, 사용한 모델 이름)"""
    issue = review.analysis.issue_type if review.analysis and review.analysis.issue_type else IssueType.ETC
    name = review.reviewer_name or "고객"
    masked = name[0] + "*" * (len(name) - 1) if len(name) > 1 else name
    follow_up = ("교환 또는 환불을 원하시면 고객센터나 1:1 문의로 연락 주시면 빠르게 도와드리겠습니다."
                 if review.rating <= 2 else "더 좋은 상품과 서비스로 보답하겠습니다.")
    draft = f"안녕하세요, {masked} 고객님. {mall_name}입니다.\n{_BODY[issue]}\n{follow_up}\n감사합니다."
    return draft, DRAFT_MODEL
