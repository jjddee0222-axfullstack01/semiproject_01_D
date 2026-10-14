# DB 설계 (ERD)

<img width="6984" height="6090" alt="pinpoint_erd (1)" src="https://github.com/user-attachments/assets/e7ed755e-7458-46e5-b60b-b92c083d973c" />

- DBMS: **MariaDB 10.5+**, 문자셋 `utf8mb4`, 엔진 InnoDB
- 실제 정의: `backend/models.py` (SQLAlchemy ORM) · 같은 내용의 DDL: `backend/schema_mariadb.sql`
- ID 는 모두 `BIGINT UNSIGNED AUTO_INCREMENT` (대리키). 월별 통계 2개만 복합 기본키

## 1. 테이블 목록 (15개)

| 구분 | 테이블 | 설명 | 기본키(PK) | 외래키(FK) · 고유(UNIQUE) |
|---|---|---|---|---|
| 계정 | `users` | 셀러(서비스 이용자). `status` = ACTIVE / WITHDRAWN(소프트 탈퇴) | id | UNIQUE email, business_number |
| 계정 | `sessions` | 로그인 세션. 토큰은 SHA-256 해시만 저장 | id | user_id → users (CASCADE) · UNIQUE session_token_hash |
| 상품 | `products` | 셀러의 상품 | id | seller_id → users (CASCADE) |
| 리뷰 | `reviews` | 수집한 리뷰. 원문(`content_raw`)과 정제본(`content_clean`) 분리 보존, `status` = VISIBLE / BLINDED | id | product_id → products (CASCADE) · blinded_by → users (SET NULL) |
| 리뷰 | `review_analysis` | 리뷰 1건당 분석 결과 1행: 감성·점수·위험도(0~3)·이슈 유형·모델 버전 | id | review_id → reviews (CASCADE) · UNIQUE review_id (1:1) |
| 리뷰 | `keywords` | 키워드 사전 ('배송 만족', '포장 불만', '환불' …) + 극성 | id | UNIQUE word |
| 리뷰 | `review_keywords` | 리뷰 ↔ 키워드 연결 (N:M 중간 테이블) + 중요도 | (review_id, keyword_id) | review_id → reviews, keyword_id → keywords (CASCADE) |
| 리뷰 | `review_blind_logs` | 블라인드·복구 이력 | id | review_id → reviews (CASCADE) · actor_id → users (SET NULL) |
| CS | `review_replies` | CS 답글 (답글의 답글 가능). CS챗봇 '처리 완료'도 여기에 저장 | id | review_id → reviews (CASCADE) · author_id → users (SET NULL) · parent_id → review_replies (CASCADE) |
| CS | `reply_suggestions` | 추천 답글(사과문) 생성 이력 | id | review_id → reviews (CASCADE) |
| 설정 | `risk_keywords` | 셀러별 위험 키워드와 가중치 | id | seller_id → users (CASCADE) · UNIQUE (seller_id, word) |
| 통계 | `shop_monthly_stats` | 쇼핑몰 월별 방문자·구매자 수 | (seller_id, month) | seller_id → users (CASCADE) |
| 통계 | `product_monthly_stats` | 상품 월별 구매자 수 | (product_id, month) | product_id → products (CASCADE) |
| 기타 | `ingest_logs` | 데이터 적재 이력 (총·중복·결측 건수) | id | - |
| 기타 | `feedbacks` | '의견 보내기' 내용 | id | user_id → users (SET NULL) |

## 2. 관계

| 관계 | 종류 | 의미 |
|---|---|---|
| users — products | 1 : N | 셀러 한 명이 여러 상품을 가짐 |
| products — reviews | 1 : N | 상품 하나에 여러 리뷰 |
| reviews — review_analysis | 1 : 1 | 리뷰마다 분석 결과 하나 |
| reviews — keywords | N : M | `review_keywords` 로 연결 (한 리뷰에 여러 키워드, 한 키워드가 여러 리뷰에) |
| reviews — review_replies | 1 : N | 리뷰 하나에 여러 답글. `parent_id` 로 답글의 답글(자기 참조) |
| reviews — review_blind_logs | 1 : N | 블라인드·복구할 때마다 이력 1행 |
| users — risk_keywords | 1 : N | 셀러마다 자기 위험 키워드 목록 |
| users / products — *_monthly_stats | 1 : N | 월마다 1행 |

## 3. 설계 규칙 (06_architecture.md 의 결정과 같음)

- **블라인드 = 소프트 삭제 (D2)**: 리뷰를 지우지 않고 `status = BLINDED` + 사유·처리자·시각 기록. 통계·위험 리뷰·키워드·CSV 는 모두 `VISIBLE` 만 집계
- **탈퇴 = 소프트 탈퇴 (D5)**: `users.status = WITHDRAWN`. 답글 작성자·블라인드 처리자는 `SET NULL` 로 익명화
- **소유권**: 상품·리뷰·답글·위험 키워드는 `products.seller_id` 가 로그인한 셀러인 것만 접근 (API 403, 화면 404)
- **재분석 범위 식별**: `review_analysis.model_version` (지금은 `rule-v1`)
- **임베딩 (D6)**: `products.description_embedding`, `reviews.content_embedding` JSON 컬럼 (현재 미사용, 컬럼만 유지)
