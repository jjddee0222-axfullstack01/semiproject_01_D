"""
PIN POINT REVIEW - DB 초기화 / 공통 데이터 처리 / 데모 데이터 (SQLAlchemy ORM)

테이블 정의는 models.py, 엔진·세션 설정은 db.py 에 있습니다.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from .analysis import DEFAULT_RISK_KEYWORDS, MODEL_VERSION, analyze_review
    from .db import SessionLocal, create_tables
    from .models import (MallPlatform, Product, ProductMonthlyStat, Review, ReviewAnalysis,
                         RiskKeyword, ShopMonthlyStat, User)
    from .security import hash_password
except ImportError:
    from analysis import DEFAULT_RISK_KEYWORDS, MODEL_VERSION, analyze_review
    from db import SessionLocal, create_tables
    from models import (MallPlatform, Product, ProductMonthlyStat, Review, ReviewAnalysis,
                        RiskKeyword, ShopMonthlyStat, User)
    from security import hash_password


def this_month() -> date:
    """월별 통계 테이블의 month 값 (해당 월 1일)"""
    return date.today().replace(day=1)


def add_default_risk_keywords(db: Session, seller: User) -> None:
    """회원가입 시 기본 위험 키워드 등록 (셀러가 나중에 수정·삭제 가능)"""
    db.add_all(RiskKeyword(seller=seller, word=w, weight=wt) for w, wt in DEFAULT_RISK_KEYWORDS)


def seller_risk_keywords(db: Session, seller_id: int) -> list[tuple[str, int]]:
    rows = db.execute(select(RiskKeyword.word, RiskKeyword.weight)
                      .where(RiskKeyword.seller_id == seller_id)).all()
    return [(w, wt) for w, wt in rows]


def analyze_and_save(db: Session, review: Review, risk_keywords: list[tuple[str, int]]) -> ReviewAnalysis:
    """리뷰를 분석해 review_analysis 에 저장 (이미 있으면 갱신)"""
    result = analyze_review(review.content_raw, review.rating, risk_keywords)
    analysis = review.analysis or ReviewAnalysis(review=review, model_version=MODEL_VERSION)
    analysis.sentiment = result.sentiment
    analysis.sentiment_score = result.sentiment_score
    analysis.severity = result.severity
    analysis.issue_type = result.issue_type
    analysis.model_version = MODEL_VERSION
    db.add(analysis)
    return analysis


def init_db() -> None:
    """테이블 생성 + 비어 있으면 데모 데이터 입력"""
    create_tables()
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            _seed(db)
            db.commit()


def _seed(db: Session) -> None:
    """화면 시안의 예시 데이터를 넣은 데모 계정 (demo@pinpoint.kr / Pinpoint1!)"""
    user = User(email="demo@pinpoint.kr", password_hash=hash_password("Pinpoint1!"), name="홍길동",
                mall_name="피인포인트몰", mall_platform=MallPlatform.NAVER, business_number="1234567890")
    db.add(user)
    add_default_risk_keywords(db, user)
    db.flush()
    risk_keywords = seller_risk_keywords(db, user.id)

    today = date.today()
    demo = [
        ("[상품명] 프리미엄 시그니처 상품 A", "리빙", "옵션: 기본형 / 상세 설명이 제공되는 공간입니다.", 340, [
            ("김민수", "배송이 정말 빠르고 상품 마감 상태도 훌륭합니다. 대만족이에요!", 5, 4),
            ("이지은", "생각보다 색감이 조금 어둡긴 한데 전반적으로 쓸만합니다.", 3, 5),
            ("박서준", "포장이 살짝 찌그러져서 왔어요. 제품은 멀쩡합니다.", 3, 6),
            ("오세린", "선물용으로 구매했는데 포장도 깔끔하고 품질이 고급스러워요.", 5, 8),
            ("강도윤", "불량품이 왔어요. 환불 요청합니다.", 1, 11),
        ]),
        ("[상품명] 에센셜 베이직 아이템 B", "패션", "옵션: S / M / L", 520, [
            ("최유리", "배송도 빠르고 상품 상태가 너무 마음에 듭니다! 파손 없이 잘 왔어요.", 5, 1),
            ("정하늘", "생각했던 것보다 조금 아쉽네요. 마감 처리가 살짝 헐거워요.", 3, 2),
            ("윤서아", "설명과 완전히 다른 제품이에요. 사기 아닌가요? 소비자원에 신고하겠습니다.", 1, 9),
        ]),
        ("[상품명] 컴포트 데일리 상품 C", "생활", "옵션: 1개입 / 3개입", 420, [
            ("한지호", "가성비 최고입니다. 주변에도 추천했어요! 재구매 의사 있습니다.", 5, 3),
            ("서도현", "크기가 딱 적당하고 배송도 빨랐어요.", 4, 7),
            ("문가은", "포장 상자가 찢어져서 왔고 구성품 하나가 누락됐습니다.", 2, 10),
        ]),
    ]
    for name, category, description, buyers, reviews in demo:
        product = Product(seller=user, name=name, category=category, description=description)
        db.add(product)
        for reviewer, content, rating, days_ago in reviews:
            review = Review(product=product, reviewer_name=reviewer, rating=rating,
                            content_raw=content, reviewed_at=today - timedelta(days=days_ago))
            db.add(review)
            analyze_and_save(db, review, risk_keywords)
        db.flush()                                   # product.id 확정
        db.add(ProductMonthlyStat(product_id=product.id, month=this_month(), buyers=buyers))

    db.add(ShopMonthlyStat(seller_id=user.id, month=this_month(), visitors=12450, buyers=1280))
