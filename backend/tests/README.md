# PIN POINT REVIEW 테스트

## 실행
```powershell
cd backend
python -m pip install -r requirements-dev.txt   # 처음 한 번
python -m pytest                                # 전체 실행 (또는 run_tests.bat 더블클릭)
```

| 명령 | 내용 |
|---|---|
| `python -m pytest -m unit` | DB·서버 없이 도는 단위 테스트만 |
| `python -m pytest -m api` | `/api/v1` API 테스트만 |
| `python -m pytest -m pages` | HTML 화면 테스트만 |
| `python -m pytest -k blind -v` | 이름에 `blind` 가 들어간 테스트만, 자세히 |
| `python -m pytest -x` | 처음 실패한 곳에서 멈춤 |

## DB
- 기본은 **임시 SQLite** 라서 MariaDB 데이터(`pinpoint`)는 건드리지 않습니다.
- MariaDB 로 테스트하려면 **테스트 전용 DB**(이름이 `_test` 로 끝나야 함)를 지정합니다.
  테스트마다 모든 테이블을 지우고 다시 만들기 때문에 운영 DB 는 절대 쓰면 안 됩니다.
  ```powershell
  $env:TEST_DATABASE_URL = "mariadb+pymysql://pinpoint:비밀번호@127.0.0.1:3306/pinpoint_test?charset=utf8mb4"
  python -m pytest
  ```
- 테스트마다 데모 데이터(demo@pinpoint.kr, 상품 A·B·C, 리뷰 11개)를 새로 넣습니다.

## 파일
| 파일 | 검사 내용 |
|---|---|
| `conftest.py` | 공통 설정, 로그인된 클라이언트 등 픽스처 |
| `test_unit.py` | 텍스트 클리닝, 리뷰 분석 규칙(severity·감성·이슈 유형), 요약, 비밀번호·세션 토큰 |
| `test_schemas.py` | Pydantic 입력 검증 |
| `test_models.py` | DB 제약 조건, 연쇄 삭제, 익명화, 블라인드 제외 |
| `test_mariadb_sql.py` | MariaDB DDL(InnoDB·utf8mb4·ERD 타입), MariaDB 전용 쿼리 |
| `test_pages.py` | 로그인·회원가입·대시보드·상품·설정·탈퇴·의견 보내기·404 화면 |
| `test_api_auth.py` | 회원가입·로그인·로그아웃·내 정보·비밀번호 변경·탈퇴 |
| `test_api_products_reviews.py` | 상품, 리뷰 조회·필터, 블라인드·복구 |
| `test_api_replies.py` | CS 답글 트리, 권한, 연쇄 삭제 |
| `test_api_stats.py` | 월별 추이, 긍·부정 비율, 위험 리뷰, 이슈 유형, 요약, 키워드 TOP, 비교 |
| `test_api_risk_keywords.py` | 위험 키워드 CRUD, 추가·수정·삭제 시 기존 리뷰 즉시 재분석 |
| `test_api_exports_suggestions.py` | CSV 내보내기, 사과 답글 초안 |
| `test_api_internal.py` | 내부 API 키, CSV 적재(중복·결측), 분석·재분석 |
| `test_pages_analysis_cs.py` | 쇼핑몰 분석 화면·리포트, CS챗봇(추천 답글 수정·복사·처리 완료) |
| `test_pages_day6.py` | 차트 화면, 블라인드 화면, 상품 검색, 위험 키워드 관리(즉시 반영) |
| `test_pages_upload.py` | 리뷰 CSV 업로드 (인코딩·중복·오류 행·크기 제한) |
| `test_pages_review_filter.py` | 상품별 대시보드 리뷰 필터·정렬 |
| `test_pages_password_reset.py` | 비밀번호 변경하기 (정보 일치·잠금·세션 종료) |
| `test_pages_email_verify.py` | 이메일 인증 코드 (발급·만료·1회용·5회 오류·메일 발송), 탈퇴 완료 화면 |
| `test_pages_extra.py` | 리뷰 목록, 업로드 이력, 상품 비교, 대시보드 '처리할 일', 모바일 메뉴 |
| `test_neutral_sentiment.py` | 중립(3점) 분류, 중립 답글 초안, 서버 시작 시 예전 분석 자동 갱신 |
| `test_security_limits.py` | 인증 코드 쿠키 재사용 차단, 발송 횟수 제한, 로그인·비밀번호 찾기 잠금, API 회원가입 인증, SECRET_KEY 점검 |

보안 테스트는 시도 기록(서버 메모리)을 테스트마다 비웁니다 (`conftest.py` 의 `fresh_db`).
테스트 계획과 결과는 [docs/07_test_plan.md](../../docs/07_test_plan.md), [docs/09_test_result.md](../../docs/09_test_result.md) 에 있습니다.

새 기능을 만들면 같은 방식으로 `test_*.py` 에 테스트를 추가하세요.
