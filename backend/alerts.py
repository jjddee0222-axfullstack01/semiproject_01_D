"""
PIN POINT REVIEW - 알림 (v1.1): CSV 업로드 후 위험 리뷰 메일

흐름 (main.products_upload)
  1) 적재 전 셀러의 마지막 리뷰 ID 를 기억 (last_review_id)
  2) 적재 후 그보다 큰 ID 중 위험(severity ≥ RISK_SEVERITY)·VISIBLE 리뷰를 찾음 (risky_reviews_after)
  3) 알림 설정(notification_settings.risk_email)이 켜져 있으면 응답을 먼저 보낸 뒤 백그라운드로 메일 발송
메일 서버(MAIL_HOST)가 없으면 개발 모드: 메일 대신 서버 콘솔에 내용을 출력
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

try:
    from .analysis import RISK_SEVERITY
    from .email_verify import dev_mode, send_mail
    from .privacy import mask_pii
    from .models import NotificationSetting, Product, Review, ReviewAnalysis, User, visible_reviews
except ImportError:
    from analysis import RISK_SEVERITY
    from email_verify import dev_mode, send_mail
    from privacy import mask_pii
    from models import NotificationSetting, Product, Review, ReviewAnalysis, User, visible_reviews

MAIL_LIST_LIMIT = 10          # 메일 본문에 보여 줄 위험 리뷰 수
SNIPPET_LENGTH = 80


def last_review_id(db: Session, seller_id: int) -> int:
    return db.scalar(select(func.max(Review.id)).join(Review.product).where(Product.seller_id == seller_id)) or 0


def risky_reviews_after(db: Session, seller_id: int, after_id: int) -> list[Review]:
    """after_id 이후 새로 들어온 위험 리뷰 (심각도 높은 순)"""
    return db.scalars(
        visible_reviews().join(Review.product).join(Review.analysis)
        .where(Product.seller_id == seller_id, Review.id > after_id, ReviewAnalysis.severity >= RISK_SEVERITY)
        .order_by(ReviewAnalysis.severity.desc(), Review.id)
        .options(selectinload(Review.product), selectinload(Review.analysis))
    ).all()


def risk_email_enabled(db: Session, seller_id: int) -> bool:
    setting = db.get(NotificationSetting, seller_id)
    return bool(setting and setting.risk_email)


def set_risk_email(db: Session, seller_id: int, enabled: bool) -> NotificationSetting:
    """알림 설정 저장 (행이 없으면 생성). commit 은 호출한 쪽에서"""
    setting = db.get(NotificationSetting, seller_id) or NotificationSetting(seller_id=seller_id)
    setting.risk_email = enabled
    db.add(setting)
    return setting


def _mask(name) -> str:
    return (name[0] + "*" * (len(name) - 1)) if name else "익명"


def compose_risk_mail(user: User, reviews: list[Review], source: str) -> tuple[str, str]:
    """(제목, 본문). 개인정보 보호를 위해 작성자 이름은 가림"""
    subject = f"[PIN POINT REVIEW] 위험 리뷰 {len(reviews)}건이 새로 들어왔습니다"
    lines = [f"{user.name}님, '{source}' 업로드에서 답변이 필요한 위험 리뷰 {len(reviews)}건이 발견되었습니다.", ""]
    for i, r in enumerate(reviews[:MAIL_LIST_LIMIT], start=1):
        text = mask_pii(r.content_raw).replace("\n", " ")
        if len(text) > SNIPPET_LENGTH:
            text = text[:SNIPPET_LENGTH] + "…"
        lines.append(f"{i}. [{r.product.name}] ★{r.rating} 심각도 {r.analysis.severity} · {_mask(r.reviewer_name)}")
        lines.append(f"   {text}")
    if len(reviews) > MAIL_LIST_LIMIT:
        lines.append(f"… 외 {len(reviews) - MAIL_LIST_LIMIT}건")
    lines += ["", "CS챗봇 화면에서 답글 초안을 확인하고 처리해 주세요.",
              "※ 이 메일은 [정보 수정 → 알림 설정]에서 끌 수 있습니다."]
    return subject, "\n".join(lines)


def deliver(to: str, subject: str, body: str) -> None:
    """메일 발송 (백그라운드 작업용 — 실패해도 예외를 밖으로 던지지 않음)"""
    if dev_mode():
        print(f"[PIN POINT][개발 모드] 알림 메일 → {to}\n제목: {subject}\n{body}")
        return
    try:
        send_mail(to, subject, body)
    except Exception as exc:        # noqa: BLE001 — 업로드 결과에는 영향 없음
        print(f"[PIN POINT] 알림 메일 발송 실패: {exc!r}")
