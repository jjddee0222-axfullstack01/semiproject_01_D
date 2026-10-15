## api 설계

## 공통

| 항목 | 내용 |
| --- | --- |
| Base URL | `/api/v1` |
| 인증 | `세션 쿠키 session_id (HttpOnly, Secure, SameSite=Lax) 자동 전송.` (🔓 표시 외 전부 필요) |
| 페이지네이션 | `?page=1&size=20` → `{items, page, size, total}` |
| 기간·상품 필터 | `?product_id=&from=YYYY-MM-DD&to=YYYY-MM-DD` |
| 오류 | 400/422 입력 오류, 401 미인증, 403 권한 없음, 404 없음, 409 충돌, 429 시도 횟수 초과 (형식 `{code, message}`) |
| 소유권 | 상품·리뷰·답글·위험키워드는 모두 본인 상품 기준으로만 접근 가능 |

## 1. 인증·계정 (E1, Must)

| 메서드 | 경로 | 설명 | 응답 | US |
| --- | --- | --- | --- | --- |
| POST | `/auth/signup` 🔓 | 회원가입 (email, password, name, mall_name, mall_platform, business_number, **email_code**). `email_code` 는 `POST /email-code` 로 받은 6자리 코드 (`EMAIL_VERIFICATION=0` 이면 생략) | 201 / 400(`EMAIL_CODE_INVALID`) / 409(이메일·사업자번호 중복) / 422 | US-01 |
| POST | `/auth/login` 🔓 | 로그인, 세션 생성 후 Set-Cookie: session_id 발급. 같은 이메일 5회·같은 IP 20회 실패 시 10분 잠금 (화면 로그인과 공통) | 200 / 401 / 429(`LOGIN_LOCKED`) | US-02 |
| POST | `/auth/logout` | 로그아웃, 세션 행 삭제와 쿠키 만료 | 204 | US-03 |
| GET | `/users/me` | 내 정보 조회 | 200 |  |
| PATCH | `/users/me` | 쇼핑몰명·플랫폼 등 수정 | 200 |  |
| DELETE | `/users/me` | 회원 탈퇴 (body: password 재확인). 계정과 상품·리뷰·답글 등 모든 데이터, 세션을 함께 삭제 (하드 삭제) | 204 / 401 | US-04 |

## 2. 상품 (E2, Must)

| 메서드 | 경로 | 설명 | US |
| --- | --- | --- | --- |
| GET | `/products` | 내 상품 목록·검색 (`?q=&category=&page=`) | T-203 |
| GET | `/products/{product_id}` | 상품 상세 (리뷰 수, 평균 평점 요약 포함) | T-203 |


## 3. 리뷰 조회 및 블라인드 (E2, Must)

| 메서드 | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| GET | `/products/{product_id}/reviews` | 상품별 리뷰 목록 (평점, 작성일, 본문, 감성, 상태). 필터: `status=VISIBLE | BLINDED |
| GET | `/reviews/{review_id}` | 리뷰 상세 (분석 결과, 키워드, 답글 포함) | 200 / 403 / 404 |
| **POST** | **`/reviews/{review_id}/blind`** | **악성 리뷰 블라인드 (body: `reason` 필수)** | 200 / **403(타인 상품)** / 404 / 409(이미 블라인드) / 422(사유 누락) |
| DELETE | `/reviews/{review_id}/blind` | 블라인드 해제(복구) | 200 / 403 / 404 / 409(블라인드 상태 아님) |
| GET | `/reviews/{review_id}/blind-logs` | 블라인드·복구 이력 | 200 / 403 |

## 4. 리뷰 답글 CS (E3, Should)

| 메서드 | 경로 | 설명 | 응답 | US |
| --- | --- | --- | --- | --- |
| GET | `/reviews/{review_id}/replies` | 답글 트리 조회 | 200 | US-07 |
| POST | `/reviews/{review_id}/replies` | 답글 등록 (content, 선택 parent_id) | 201 / 403 / 409(블라인드된 리뷰) | US-07 |
| PATCH | `/replies/{reply_id}` | 답글 수정 | 200 / 403 | US-08 |
| DELETE | `/replies/{reply_id}` | 답글 삭제 | 204 / 403 | US-08 |


## 5. 통계·대시보드 (E5)

| 메서드 | 경로 | 설명 | 우선순위 | US |  |
| --- | --- | --- | --- | --- | --- |
| GET | `/stats/monthly-trend` | 월별 리뷰 수·평균 평점 `[{month, count, avg_rating}]` | Must | US-12 |  |
| GET | `/stats/sentiment-ratio` | 긍/부정/중립 비율과 건수 (중립 = 위험 키워드 없는 3점 리뷰, `rule-v2`) | Should | US-14 |  |
| GET | `/stats/keywords/top` | 키워드 TOP 10과 빈도 (`?limit=10&polarity=`) | Should | US-13 |  |
| GET | `/stats/risk-reviews` | 부정 리뷰를 최신순·심각도순으로 정렬한 목록 (`?issue_type=PRODUCT | DELIVERY | PACKAGING`, 페이지네이션) |  |
| GET | `/stats/issue-types` | 상품 문제 vs 유통·포장 문제 건수 분포 | Should | 핵심 가치 |  |
| GET | `/stats/summary` | 대시보드 상단 카드용 요약 (총 리뷰, 평균 평점, 부정 비율, 위험 리뷰 수) | Should |  |  |
| GET | `/stats/compare` | 두 상품 비교 (`?product_ids=1,2`): 평점, 키워드, 긍/부정 비율 | Could | US-17 |  |

## 6. 위험 키워드 설정 (Gap Analysis, Should)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/risk-keywords` | 내 위험 키워드 목록 |
| POST | `/risk-keywords` | 등록 (word, weight) / 409(중복) |
| PATCH | `/risk-keywords/{id}` | 수정 |
| DELETE | `/risk-keywords/{id}` | 삭제 |

등록·수정·삭제하면 그 단어가 들어간 기존 리뷰를 바로 다시 분석합니다 (위험 여부·감성·키워드 통계에 즉시 반영, FR-27). 응답 형식은 그대로입니다.

## 7. 내보내기·LLM 기능

| 메서드 | 경로 | 설명 | 우선순위 | US |
| --- | --- | --- | --- | --- |
| GET | `/exports/stats.csv` | 통계 CSV 다운로드 (필터 동일) | Should | T-306 |
| GET | `/exports/reviews.csv` | 분석된 리뷰 CSV 다운로드 | Should |  |
| POST | `/reviews/{review_id}/reply-suggestions` | 부정 리뷰에 대한 LLM 사과 답글 초안 생성 | Could | US-16 |
| GET | `/reviews/{review_id}/reply-suggestions` | 생성 이력 조회 | Could | US-16 |

## 8. 데이터 파이프라인 (E4, 내부용 / 외부 노출 금지)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | `/internal/ingest` | 데이터셋 적재 실행 |
| POST | `/internal/analyze` | 미분석 리뷰 분석 실행 |
| GET | `/internal/ingest-logs` | 적재 이력 (중복·결측 건수) |

## 9. 화면 보조 엔드포인트 (`/api/v1` 밖, 로그인 불필요)

| 메서드 | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| POST | `/email-code` | 이메일 인증 코드 발송 (body: `{purpose: signup\|reset, email}`). 10분 유효, 재발송 60초 뒤, 이메일당 1시간 5회·IP당 20회. 개발 모드(`MAIL_HOST` 없음)에서는 응답에 `dev_code` 포함 | 200 / 400 / 409(가입된 이메일로 signup) / 429 |
