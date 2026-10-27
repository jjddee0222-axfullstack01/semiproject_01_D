"""
PIN POINT REVIEW - 리뷰 답글 초안 (US-16, CS챗봇 화면)

부정 리뷰는 이슈 유형별 사과 답글, 중립 리뷰는 감사 + 개선 약속 답글, 긍정 리뷰는 감사 답글 초안을 만듭니다.

지금은 템플릿으로 초안을 만듭니다 (llm_model = "template-v1").
LLM API 를 연결할 때는 generate_reply_draft() 안에서 API 를 호출하고,
돌려주는 모델 이름(DRAFT_MODEL)만 바꾸면 나머지 API·DB 저장은 그대로 동작합니다.

v1.1 셀러 답글 템플릿 (reply_templates)
  셀러가 감성(긍정·중립·부정)마다 자기 말투의 템플릿을 저장하면 CS챗봇·답글 추천 API 가 그 템플릿을 사용
  (llm_model = "seller-template-v1"). 쓸 수 있는 자리 표시자는 TEMPLATE_PLACEHOLDERS 4개뿐이며
  {기본 답글} 자리에는 위 기본 초안이 그대로 들어감 → "감사 인사 + 기본 답글 + 우리 몰 마무리 문구" 같은 조합 가능
"""
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from .models import IssueType, Polarity, ReplyTemplate, Review, User
except ImportError:
    from models import IssueType, Polarity, ReplyTemplate, Review, User

DRAFT_MODEL = "template-v1"
SELLER_TEMPLATE_MODEL = "seller-template-v1"
TEMPLATE_MAX_LENGTH = 2000
TEMPLATE_PLACEHOLDERS = ("{고객명}", "{쇼핑몰명}", "{상품명}", "{기본 답글}")
SENTIMENT_LABELS = {Polarity.POS: "긍정", Polarity.NEU: "중립", Polarity.NEG: "부정"}

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


# ──────────────────────────────────────────────
# v1.1 셀러 답글 템플릿
# ──────────────────────────────────────────────
def template_problem(content: str) -> Optional[str]:
    """템플릿 검증 → 문제가 있으면 안내 문구, 없으면 None"""
    if not content.strip():
        return "템플릿 내용을 입력해 주세요."
    if len(content) > TEMPLATE_MAX_LENGTH:
        return f"템플릿은 {TEMPLATE_MAX_LENGTH:,}자 이하로 입력해 주세요."
    unknown = sorted({p for p in re.findall(r"\{[^{}]*\}", content) if p not in TEMPLATE_PLACEHOLDERS})
    if unknown:
        return (f"쓸 수 없는 자리 표시자가 있습니다: {', '.join(unknown)} "
                f"(사용 가능: {' '.join(TEMPLATE_PLACEHOLDERS)})")
    return None


def apply_template(template: str, review: Review, mall_name: str) -> str:
    """자리 표시자를 실제 값으로 바꿈 (str.format 은 쓰지 않음 — 셀러 입력의 중괄호로 인한 오류 방지)"""
    values = {"{고객명}": _masked(review), "{쇼핑몰명}": mall_name,
              "{상품명}": review.product.name if review.product else "",
              "{기본 답글}": generate_reply_draft(review, mall_name)[0]}
    for key, value in values.items():
        template = template.replace(key, value)
    return template.strip()


def seller_templates(db: Session, seller_id: int) -> dict[Polarity, ReplyTemplate]:
    return {t.sentiment: t for t in db.scalars(select(ReplyTemplate).where(ReplyTemplate.seller_id == seller_id))}


def seller_reply_draft(review: Review, user: User,
                       templates: dict[Polarity, ReplyTemplate]) -> tuple[str, str]:
    """셀러 템플릿이 있으면 그것으로, 없으면 기본 초안 (본문, 모델 이름)"""
    sentiment = review.analysis.sentiment if review.analysis else Polarity.NEG
    template = templates.get(sentiment)
    if template is None:
        return generate_reply_draft(review, user.mall_name)
    return apply_template(template.content, review, user.mall_name), SELLER_TEMPLATE_MODEL
