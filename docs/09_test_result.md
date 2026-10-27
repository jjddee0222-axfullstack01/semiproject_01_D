# 09. 테스트 결과서 — PIN POINT REVIEW

[07_test_plan.md](07_test_plan.md) 의 계획대로 실행한 결과입니다. 발견한 문제는 [08_issue_log.md](08_issue_log.md) 에 있습니다.

| 항목 | 내용 |
|---|---|
| 실행일 | 2026-10-15 (7일차 품질 점검·2차 점검), 2026-10-16 (8일차 Agent Task 후), 2026-10-19 (9일차 통합 점검 후 재실행) |
| 대상 | `main` 최신 코드 + 7일차 수정 (중립 분류, 인증·로그인 보안 강화, 위험 키워드 즉시 반영) + 7일차 2차 점검 수정 (I-17\~I-23) + 8일차 Agent Task T-8-1 (CSV 입력 검증, `GET /api/v1/health`) + 9일차 통합 점검 수정 (I-26\~I-30) |
| 환경 | Python 3.13, FastAPI 0.143, SQLAlchemy 2.0.36, Pydantic 2.13, pytest 9.0, 임시 SQLite DB |
| 브라우저 시나리오 | uvicorn 로컬 서버(최상위 폴더에서 `uvicorn main:app`) + Chromium (Playwright 1.56), 데스크톱 1280px · 휴대폰 390px |

## 1. 요약

| 구분 | 결과 |
|---|---|
| 자동 테스트 | **379개 중 379개 통과** (실패 0, 건너뜀 0) — v1.0.0 347개 + v1.1 32개 (2026-10-27, 2장 마지막 문단) |
| 사용자 시나리오 | **12개 중 12개 통과** (S-01 \~ S-12, 9일차 코드로 다시 실행. S-01 로그아웃은 사이드바 버튼(POST)으로) |
| Must 기능(FR-01\~08) 정상 동작률 | **100%** |
| MariaDB 호환 | 테스트 중 실행된 SQL 33,657건을 MariaDB 방언으로 생성 → 오류 0건 |
| 발견·해결한 문제 | 35건 (높음 6, 중간 15, 낮음 14) — 모두 해결 (v1.1 정리 I-34·I-35 포함) |
| 배포 환경 | Railway + MariaDB 11 에서 서버 시작·DB 연결 확인 (2026-10-20, 6장) |
| 정적 점검 (Dead Code·중복 코드) | 쓰이지 않는 코드 1건 삭제, 중복 2곳 확인 (5장) |

## 2. 자동 테스트 (단위 · API · 통합 · 회귀)

```
cd backend && python -m pytest
379 passed
```

| 단계 | 테스트 수 | 결과 |
|---|---|---|
| 단위 (`-m unit`) | 55 | 통과 |
| API (`-m api`) | 85 | 통과 |
| 화면·통합 (`-m pages`) | 228 | 통과 |
| DB 모델 (`test_models.py`) | 11 | 통과 |

| 파일 | 수 | 파일 | 수 |
|---|---|---|---|
| `test_unit.py` | 24 | `test_pages.py` | 28 |
| `test_schemas.py` | 25 | `test_pages_analysis_cs.py` | 20 |
| `test_models.py` | 11 | `test_pages_day6.py` | 21 |
| `test_mariadb_sql.py` (17개 테이블) | 3 | `test_pages_upload.py` | 15 |
| `test_api_auth.py` | 10 | `test_pages_review_filter.py` | 13 |
| `test_api_products_reviews.py` | 19 | `test_pages_password_reset.py` | 13 |
| `test_api_replies.py` | 4 | `test_pages_email_verify.py` | 12 |
| `test_api_stats.py` | 11 | `test_pages_extra.py` | 34 |
| `test_api_risk_keywords.py` | 5 | `test_neutral_sentiment.py` | 3 |
| `test_api_exports_suggestions.py` | 5 | `test_security_limits.py` | 16 |
| `test_api_internal.py` | 9 | `test_review_fixes.py` | 23 |
| `test_agent_task_day8.py` | 13 | `test_day9_fixes.py` | 12 |
| `test_api_v11_alerts_templates.py` (v1.1) | 22 | `test_pages_v11_reports.py` (v1.1) | 5 |
| `test_migrations.py` (v1.1) | 3 | | |
| | | **합계** | **379** |

**회귀 확인:** 7일차 1차 점검 수정 전 276개 → 수정 후 298개 (새 테스트 22개). 중립 분류 도입으로 실패한 기존 테스트 9건은 오류가 아니라 의도한 숫자 변화라서 기대값을 새 규칙에 맞춰 고쳤습니다 (예: 데모 데이터 부정 비율 0.5455 → 0.2727, 상품 A 부정 리뷰 3 → 1).

**7일차 2차 점검:** favicon 테스트 1개(팀 추가)와 점검 수정 테스트 23개를 더해 299개 → 322개. CSV 수식 주입, 운영 모드 인증 코드 노출 등은 고치기 전에 먼저 재현해 확인했습니다 (I-17~I-23).

**8일차 Agent Task:** CSV 입력 검증 테스트 10개와 상태 확인 API 테스트 3개(`test_agent_task_day8.py`)를 더해 322개 → 335개. 기존 테스트 1건(`test_upload_reports_bad_rows`)은 오류 문구가 "평점은 1\~5" → "평점은 1\~5 정수"로 바뀌어 기대값만 고쳤습니다.

**9일차 통합 점검:** I-26\~I-30 수정 테스트 12개(`test_day9_fixes.py`)를 더해 335개 → 347개. 새 테스트 중 11개는 고치기 전 코드에서 실패하는 것을 먼저 확인했습니다 (나머지 1개는 원래 되던 POST 로그아웃을 지키는 테스트). 기존 테스트 3곳은 로그아웃을 GET → POST 로, 1곳은 설정 화면의 '비밀번호 확인' 값을 추가하도록 고쳤습니다.

**v1.1 고도화 (2026-10-27):** 347개 → 379개 (+32).
- 정리: 옛 `POST /api/reviews` 테스트 1개를 `POST /api/v1/reviews` 테스트 3개(분석 결과·소유권 403/404·옛 경로 삭제 확인)로 교체 (+2). 다른 파일 2곳은 주소만 `/api/v1/reviews` 로 변경
- Alembic `test_migrations.py` 3개: 빈 DB `upgrade head` 후 `alembic check`(모델과 일치), `create_all` 로 만든 기존 DB 에 `upgrade head`, `downgrade base`
- 알림·급증·템플릿 `test_api_v11_alerts_templates.py` 22개: 알림 설정 API·화면, 업로드 후 위험 리뷰 안내, 메일 발송(개발 모드 콘솔·SMTP 설정 시 발송·발송 실패해도 업로드 정상·중복 업로드 재알림 없음·작성자 이름 가림), 탈퇴 시 설정 삭제, 급증 감지(×3 / 블라인드·다른 셀러 제외 / 기준 미달), 템플릿 CRUD·검증(알 수 없는 자리 표시자·2,000자·빈 값)·소유권·답글 추천과 CS챗봇 적용
- 리포트 `test_pages_v11_reports.py` 5개: 로그인 필요, 주간 기본·월간·잘못된 기간, 지표 계산(전기간 대비), 블라인드·다른 셀러 제외
- 기존 테스트 변경: `test_mariadb_sql.py` 의 테이블 수 15 → 17 (새 테이블 2개, 기대값만 변경)
- CI: `.github/workflows/tests.yml` 이 push·PR 마다 SQLite 전체 + MariaDB 11 컨테이너(마이그레이션 `upgrade → current → downgrade` 후 전체, 모델 일치 검사 `alembic check` 는 SQLite job 의 `test_migrations.py`)를 실행

## 3. 사용자 시나리오

| ID | 시나리오 | 결과 | 확인한 값 |
|---|---|---|---|
| S-01 | 회원가입(이메일 인증 코드) → 로그인 → 로그아웃 | 통과 | 개발 모드에서 화면에 표시된 6자리 코드로 가입, 로그아웃 후 대시보드 접근 시 로그인 화면 |
| S-02 | 로그인 5회 실패 잠금 | 통과 | 3번째에 "2번 더 틀리면" 경고, 5번째 잠금, **쿠키 없는 새 브라우저에서도 잠금 유지** |
| S-03 | 비밀번호 찾기 → 새 비밀번호로 로그인 | 통과 | 인증 코드 + 이름·사업자 번호 일치 시 변경, 새 비밀번호로 대시보드 진입 |
| S-04 | 리뷰 CSV 업로드 → 업로드 이력 | 통과 | 양식 파일 그대로 업로드 → "업로드 완료" 안내, 이력 화면에 파일명 표시 |
| S-05 | 리뷰 블라인드 → 복구 | 통과 | 전체 리뷰 수 11 → 10 (통계 제외) → 11, '블라인드된 리뷰 (1)' 표시 |
| S-06 | 쇼핑몰 분석 차트 | 통과 | 긍정 5 · 중립 3 · 부정 3 (45% · 27% · 27%), 자바스크립트 오류 없음 |
| S-07 | CS챗봇 | 통과 | '[중립 리뷰]' 표시, 중립 리뷰에 사과문이 아닌 감사·개선 답글 초안 |
| S-08 | 위험 키워드 추가·삭제 즉시 반영 | 통과 | 위험 리뷰 수 3 → 4(추가) → 3(삭제), "바로 반영했습니다" 안내 |
| S-09 | 상품 목록·상품 비교·리뷰 목록 | 통과 | 상품 A '긍정 2 / 중립 2 / 부정 1', 비교 화면 3색 비율 막대, 중립 필터 3건 |
| S-10 | 회원 탈퇴 → 완료 화면 → 재가입 | 통과 | `/withdrawn` 안내 후 같은 이메일·사업자 번호로 재가입 성공 |
| S-11 | 휴대폰 390px | 통과 | 대시보드·상품·리뷰 목록·비교·분석·CS챗봇·설정·업로드 이력 8개 화면 가로 스크롤 없음 |
| S-12 | 다른 셀러가 남의 상품 접근 | 통과 | 화면 404, API 403 |

**참고:** 처음 실행에서 S-12 는 S-02 에서 잠긴 계정으로 시험해 로그인 화면이 열린 것을 통과로 잘못 판정했습니다. 새 셀러 계정을 만들어 다시 실행해 404/403 을 확인했습니다.

## 4. 요구사항별 확인

| 요구사항 | 확인 방법 | 결과 |
|---|---|---|
| FR-01\~04 계정 (Must) | `test_api_auth.py`, `test_pages.py`, S-01·S-10 | 통과 |
| FR-05\~06 상품·리뷰·블라인드 (Must) | `test_api_products_reviews.py`, `test_pages_review_filter.py`, S-05 | 통과 |
| FR-07\~08 통계·대시보드 (Must) | `test_api_stats.py`, `test_pages_day6.py`, S-06 | 통과 |
| FR-09\~19 Should·Could | `test_api_*.py`, `test_pages_analysis_cs.py`, `test_pages_upload.py`, S-04·S-07 | 통과 |
| FR-20\~25 (비밀번호 변경·이메일 인증·리뷰 목록·업로드 이력·처리할 일·모바일) | `test_pages_password_reset.py`, `test_pages_email_verify.py`, `test_pages_extra.py`, S-03·S-09·S-11 | 통과 |
| FR-26 중립 분류 | `test_unit.py`, `test_neutral_sentiment.py`, S-06·S-07·S-09 | 통과 |
| FR-27 위험 키워드 즉시 반영 | `test_pages_day6.py`, `test_api_risk_keywords.py`, S-08 | 통과 |
| FR-28 위험 리뷰 알림 (v1.1) | `test_api_v11_alerts_templates.py` (notification·upload) | 통과 |
| FR-29 부정 키워드 급증 (v1.1) | `test_api_v11_alerts_templates.py` (keyword_surge) | 통과 |
| FR-30 주간·월간 리포트 (v1.1) | `test_pages_v11_reports.py`, 인쇄 미리보기(A4 PDF 2쪽) 확인 | 통과 |
| FR-31 답글 템플릿 (v1.1) | `test_api_v11_alerts_templates.py` (reply_template·cschatbot) | 통과 |
| NFR-01\~11 보안·품질 | `test_security_limits.py`, `test_review_fixes.py`, `test_unit.py`, `test_models.py`, S-02·S-12 | 통과 |

## 5. 정적 점검 (9일차 기준: Dead Code·중복 코드 탐색)

`backend/*.py` 전체에서 정의만 되고 어디에서도 쓰이지 않는 함수·클래스·상수, 6줄 이상 똑같이 반복되는 코드를 찾았습니다 (테스트 제외, 화면 라우트처럼 FastAPI 가 부르는 함수는 제외).

| 결과 | 내용 | 조치 |
|---|---|---|
| 쓰이지 않는 코드 | `schemas.FeedbackCreate` (의견 보내기를 화면 폼으로만 구현하면서 남음) | 삭제 (I-25) |
| 오탐 | `db._sqlite_foreign_keys` — DB 연결 이벤트로 호출됨 | 유지 |
| 쓰이지 않는 템플릿 | 없음 (20개 모두 사용) | - |
| 중복 코드 | `database.reanalyze_outdated` 와 `pipeline.analyze_pending` 의 '셀러별 위험 키워드 캐시 + 재분석' 반복문 | v1.1 에서 `database.reanalyze_reviews` 로 합침 (I-35) |
| 중복 코드 | `main.py` 상품별 대시보드·리뷰 목록의 필터 매개변수 목록 | 화면마다 필터가 조금 달라 유지 |
| 옛 API | `POST /api/reviews` (`/api/v1` 밖, 화면에서 사용 안 함) | v1.1 에서 `POST /api/v1/reviews` 로 옮기고 삭제 (I-34) |

## 6. 기타 확인

- **서버 시작 시 경고:** `SECRET_KEY` 를 예시 값으로 두고 서버를 켜면 시작 로그에 경고 문구가 나오는 것을 확인했습니다.
- **예전 분석 자동 갱신:** `rule-v1` 로 저장된 결과가 서버 시작 시 `rule-v2` 로 다시 분석되는 것을 테스트로 확인했습니다 (`test_outdated_analysis_reanalyzed_on_startup`). 팀원 PC 의 MariaDB 에 이미 있는 리뷰도 서버를 다시 켜면 자동으로 중립 분류가 적용됩니다.
- **실제 MariaDB 에서 전체 테스트 (2026-10-21, MariaDB 11.4.3):** 로컬 MariaDB 의 `pinpoint_test` DB 를 `TEST_DATABASE_URL` 로 지정해 실행 ([backend/tests/README.md](../backend/tests/README.md)).
  - 1차: 347개 중 **11개 실패** — 모두 테스트 코드가 SQLite 기준으로 쓰인 부분 (확인용 세션의 격리 수준, CHECK 위반 예외 종류, ID 범위 초과 오류 코드). 서버 동작 문제는 아님 → I-33
  - 테스트 수정 후 2차: **MariaDB 347개 통과**, SQLite 347개 통과

## 6-1. 배포 환경 확인 (10일차, 2026-10-20)

배포 주소: <https://semiproject01d-production.up.railway.app> · 구성: Railway 웹 서비스(uvicorn 1개) + MariaDB 11 컨테이너 ([10_deployment.md](10_deployment.md))

| 항목 | 결과 |
|---|---|
| 서버 시작 | 통과 — 로그 `Application startup complete` · `SECRET_KEY` 설정 후 시작 경고 없음: 경고 없음 |
| 실제 MariaDB 연결 | 통과 — MariaDB 11.8 에서 테이블 자동 생성·데모 데이터 입력, `/api/v1/health` → `{"status":"ok","database":"ok","model_version":"rule-v2"}` |
| 화면 응답 | 통과 — `/login` 화면 표시 (HTTPS) |
| 사용자 시나리오 S-01\~S-12 (배포 주소) | 확인자: 정다은 · 결과: 통과 (12개 중 12개) (이메일 인증 단계는 `EMAIL_VERIFICATION=0` 으로 생략) |
| 휴대폰(LTE) 접속 | 통과(LTE 환경에서도 모든 기능 정상 동작) |

배포 중 발견한 문제 2건(I-31, I-32)은 [08_issue_log.md](08_issue_log.md) 에 기록했습니다.

## 7. 결론

Must 기능 정상 동작률 100%, 자동 테스트와 사용자 시나리오 모두 통과해 7장 완료 기준을 충족합니다. 남은 위험(시도 제한 기록이 서버 메모리에 있음, 규칙 기반 분석의 한계)은 `08_issue_log.md` 의 '남은 위험'에 정리했습니다.
