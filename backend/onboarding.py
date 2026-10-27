"""
PIN POINT REVIEW - 처음 쓰는 셀러 안내 (v1.2): 샘플 데이터로 체험하기

상품이 하나도 없는 셀러가 대시보드에서 '샘플 데이터로 체험하기'를 누르면 아래 리뷰를 내 계정에 넣고
(업로드와 같은 ingest_rows 로 적재·분석), 다 본 뒤 '샘플 데이터 지우기'로 한 번에 지웁니다.
샘플 상품은 이름이 SAMPLE_PREFIX 로 시작하므로 셀러의 실제 상품과 섞이지 않습니다.
"""
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

try:
    from .models import Product, User
    from .pipeline import ingest_rows
except ImportError:
    from models import Product, User
    from pipeline import ingest_rows

SAMPLE_PREFIX = "[샘플] "

# (상품, 카테고리, 작성자, 평점, 내용, 며칠 전)
_SAMPLE = [
    ("보온 텀블러 500ml", "주방", "김하늘", 5, "보온이 하루 종일 가요. 디자인도 예쁘고 배송도 빨랐습니다. 재구매 의사 있어요!", 1),
    ("보온 텀블러 500ml", "주방", "이도윤", 5, "선물용으로 샀는데 포장이 꼼꼼해서 좋았어요. 품질도 고급스러워요.", 2),
    ("보온 텀블러 500ml", "주방", "박서연", 4, "전체적으로 만족하는데 근데 뚜껑이 조금 뻑뻑해요.", 3),
    ("보온 텀블러 500ml", "주방", "최민준", 2, "뚜껑 사이로 물이 새요. 교환 요청합니다.", 4),
    ("보온 텀블러 500ml", "주방", "정우진", 1, "불량품이 왔어요. 환불해 주세요. 연락처 010-1234-5678", 5),
    ("보온 텀블러 500ml", "주방", "한지민", 3, "생각보다 크기가 작아요. 사이즈 표기가 있었으면 좋겠어요.", 9),
    ("보온 텀블러 500ml", "주방", "오세훈", 2, "포장 상자가 찌그러져서 왔어요.", 12),
    ("데일리 면 티셔츠", "패션", "윤하은", 5, "원단이 부드럽고 핏이 예뻐요. 가성비 최고입니다. 주변에도 추천했어요.", 1),
    ("데일리 면 티셔츠", "패션", "강지후", 3, "색감이 사진보다 어두워요. 실물 사진이 있었으면 좋겠네요.", 2),
    ("데일리 면 티셔츠", "패션", "임서준", 2, "사이즈가 너무 작아요. 사이즈표가 실제와 달라요. 반품하고 싶어요.", 3),
    ("데일리 면 티셔츠", "패션", "송예린", 4, "배송 빠르고 좋아요 다만 원단이 조금 얇아요.", 6),
    ("데일리 면 티셔츠", "패션", "조현우", 5, "세탁해도 늘어나지 않고 마감이 깔끔해요. 색상별로 재구매했습니다.", 8),
    ("데일리 면 티셔츠", "패션", "배수아", 1, "설명과 완전히 다른 제품이 왔어요. 사기 아닌가요?", 10),
    ("원목 수납 선반", "리빙", "신동현", 5, "조립이 쉽고 튼튼해요. 배송도 안전하게 왔습니다.", 2),
    ("원목 수납 선반", "리빙", "권나연", 2, "구성품 나사가 하나 누락됐어요. 조립 설명서도 이해하기 어려워요.", 4),
    ("원목 수납 선반", "리빙", "황민서", 3, "조립 방법이 헷갈려요. 사용법 영상이 있으면 좋겠어요.", 7),
    ("원목 수납 선반", "리빙", "안시우", 5, "가격 대비 품질이 정말 좋아요. 강력 추천합니다!", 11),
]


def sample_rows(today: date | None = None) -> list[dict]:
    today = today or date.today()
    return [{"product_name": SAMPLE_PREFIX + name, "category": category, "reviewer_name": reviewer,
             "rating": str(rating), "content": content, "reviewed_at": (today - timedelta(days=days)).isoformat()}
            for name, category, reviewer, rating, content, days in _SAMPLE]


def has_sample(db: Session, seller: User) -> bool:
    return db.scalar(select(Product.id).where(Product.seller_id == seller.id,
                                              Product.name.startswith(SAMPLE_PREFIX)).limit(1)) is not None


def load_sample(db: Session, seller: User) -> int:
    """샘플 리뷰 적재 → 추가된 리뷰 수 (이미 있으면 중복으로 건너뜀)"""
    log, _ = ingest_rows(db, batch_name=f"sample:{seller.id}", rows=sample_rows(), seller=seller)
    return log.total_count - log.duplicate_count - log.missing_count


def remove_sample(db: Session, seller: User) -> int:
    """샘플 상품(과 리뷰·분석·답글 등 CASCADE)을 지우고 지운 상품 수를 반환. commit 은 호출한 쪽에서"""
    products = db.scalars(select(Product).where(Product.seller_id == seller.id,
                                                Product.name.startswith(SAMPLE_PREFIX))).all()
    for p in products:
        db.delete(p)
    return len(products)
