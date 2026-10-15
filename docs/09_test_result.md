# 09. 테스트 결과서 — PIN POINT REVIEW

[07_test_plan.md](07_test_plan.md) 의 계획대로 실행한 결과입니다. 발견한 문제는 [08_issue_log.md](08_issue_log.md) 에 있습니다.

| 항목 | 내용 |
|---|---|
| 실행일 | 2026-10-15 (9일차 품질 점검, 10일차 2차 점검 후 재실행) |
| 대상 | `main` 최신 코드 + 9일차 수정 (중립 분류, 인증·로그인 보안 강화, 위험 키워드 즉시 반영) + 10일차 2차 점검 수정 (I-17~I-23) |
| 환경 | Python 3.13, FastAPI 0.143, SQLAlchemy 2.0.36, Pydantic 2.13, pytest 9.0, 임시 SQLite DB |
| 브라우저 시나리오 | uvicorn 로컬 서버(최상위 폴더에서 `uvicorn main:app`) + Chromium (Playwright 1.56), 데스크톱 1280px · 휴대폰 390px |

## 1. 요약

| 구분 | 결과 |
|---|---|
| 자동 테스트 | **322개 중 322개 통과** (실패 0, 건너뜀 0) |
| 사용자 시나리오 | **12개 중 12개 통과** (S-01 ~ S-12) |
| Must 기능(FR-01~08) 정상 동작률 | **100%** |
| MariaDB 호환 | 테스트 중 실행된 SQL 31,290건을 MariaDB 방언으로 생성 → 오류 0건 |
| 발견·해결한 문제 | 23건 (높음 6, 중간 9, 낮음 8) — 모두 해결 |

## 2. 자동 테스트 (단위 · API · 통합 · 회귀)

```
cd backend && python -m pytest
322 passed
```

| 단계 | 테스트 수 | 결과 |
|---|---|---|
| 단위 (`-m unit`) | 52 | 통과 |
| API (`-m api`) | 61 | 통과 |
| 화면·통합 (`-m pages`) | 198 | 통과 |
| DB 모델 (`test_models.py`) | 11 | 통과 |

| 파일 | 수 | 파일 | 수 |
|---|---|---|---|
| `test_unit.py` | 24 | `test_pages.py` | 28 |
| `test_schemas.py` | 25 | `test_pages_analysis_cs.py` | 20 |
| `test_models.py` | 11 | `test_pages_day6.py` | 21 |
| `test_mariadb_sql.py` | 3 | `test_pages_upload.py` | 15 |
| `test_api_auth.py` | 10 | `test_pages_review_filter.py` | 13 |
| `test_api_products_reviews.py` | 17 | `test_pages_password_reset.py` | 13 |
| `test_api_replies.py` | 4 | `test_pages_email_verify.py` | 12 |
| `test_api_stats.py` | 11 | `test_pages_extra.py` | 34 |
| `test_api_risk_keywords.py` | 5 | `test_neutral_sentiment.py` | 3 |
| `test_api_exports_suggestions.py` | 5 | `test_security_limits.py` | 16 |
| `test_api_internal.py` | 9 | `test_review_fixes.py` | 23 |
| | | **합계** | **322** |

**회귀 확인:** 9일차 수정 전 276개 → 수정 후 298개 (새 테스트 22개). 중립 분류 도입으로 실패한 기존 테스트 9건은 오류가 아니라 의도한 숫자 변화라서 기대값을 새 규칙에 맞춰 고쳤습니다 (예: 데모 데이터 부정 비율 0.5455 → 0.2727, 상품 A 부정 리뷰 3 → 1).

**10일차 2차 점검:** favicon 테스트 1개(팀 추가)와 점검 수정 테스트 23개를 더해 299개 → 322개. CSV 수식 주입, 운영 모드 인증 코드 노출 등은 고치기 전에 먼저 재현해 확인했습니다 (I-17~I-23).

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
| FR-01~04 계정 (Must) | `test_api_auth.py`, `test_pages.py`, S-01·S-10 | 통과 |
| FR-05~06 상품·리뷰·블라인드 (Must) | `test_api_products_reviews.py`, `test_pages_review_filter.py`, S-05 | 통과 |
| FR-07~08 통계·대시보드 (Must) | `test_api_stats.py`, `test_pages_day6.py`, S-06 | 통과 |
| FR-09~19 Should·Could | `test_api_*.py`, `test_pages_analysis_cs.py`, `test_pages_upload.py`, S-04·S-07 | 통과 |
| FR-20~25 (비밀번호 변경·이메일 인증·리뷰 목록·업로드 이력·처리할 일·모바일) | `test_pages_password_reset.py`, `test_pages_email_verify.py`, `test_pages_extra.py`, S-03·S-09·S-11 | 통과 |
| FR-26 중립 분류 | `test_unit.py`, `test_neutral_sentiment.py`, S-06·S-07·S-09 | 통과 |
| FR-27 위험 키워드 즉시 반영 | `test_pages_day6.py`, `test_api_risk_keywords.py`, S-08 | 통과 |
| NFR-01~11 보안·품질 | `test_security_limits.py`, `test_review_fixes.py`, `test_unit.py`, `test_models.py`, S-02·S-12 | 통과 |

## 5. 기타 확인

- **서버 시작 시 경고:** `SECRET_KEY` 를 예시 값으로 두고 서버를 켜면 시작 로그에 경고 문구가 나오는 것을 확인했습니다.
- **예전 분석 자동 갱신:** `rule-v1` 로 저장된 결과가 서버 시작 시 `rule-v2` 로 다시 분석되는 것을 테스트로 확인했습니다 (`test_outdated_analysis_reanalyzed_on_startup`). 팀원 PC 의 MariaDB 에 이미 있는 리뷰도 서버를 다시 켜면 자동으로 중립 분류가 적용됩니다.
- **실제 MariaDB 에서 전체 테스트:** 이번 실행에서는 하지 않았습니다. 팀원 PC 에서 `TEST_DATABASE_URL` 에 `pinpoint_test` DB 를 지정해 한 번 실행하는 것을 권장합니다 ([backend/tests/README.md](../backend/tests/README.md)).

## 6. 결론

Must 기능 정상 동작률 100%, 자동 테스트와 사용자 시나리오 모두 통과해 7장 완료 기준을 충족합니다. 남은 위험(시도 제한 기록이 서버 메모리에 있음, 규칙 기반 분석의 한계)은 `08_issue_log.md` 의 '남은 위험'에 정리했습니다.
