# 08. 이슈 로그 — PIN POINT REVIEW

개발·점검 중 발견한 문제와 원인, 해결 방법을 기록합니다. 새 문제를 고치면 아래 표에 한 줄 추가합니다.

- **심각도**: 높음(보안·데이터 손상·핵심 기능 불가) / 중간(기능이 기대와 다르게 동작) / 낮음(표시·문서)
- **확인**: 문제를 재현하고, 고친 뒤 통과하는 테스트

## 요약

| 구분 | 건수 | 상태 |
|---|---|---|
| 높음 | 6 | 모두 해결 |
| 중간 | 6 | 모두 해결 |
| 낮음 | 4 | 모두 해결 |

## 이슈 목록

| ID | 발견 시점 | 심각도 | 문제 | 원인 | 해결 | 확인 |
|---|---|---|---|---|---|---|
| I-01 | 6일차 점검 | 높음 | 공유 파일 `backend/setup_mariadb.sql` 에 실제 DB 비밀번호가 들어간 채 커밋됨 | 비밀 값과 공유 양식 파일의 구분이 없었음 | 예시 값(`여기에 비밀번호`)으로 바꾸고 실제 값은 `backend/.env` 에만 두도록 규칙화 (`README` 보안 규칙, `CLAUDE.md`), `.gitignore` 정리 (커밋 9814255, 2026-10-14) | 커밋 전 `git diff` 확인. **Git 기록에는 예전 값이 남아 있으므로 DB 비밀번호는 새 값으로 바꿔 사용** |
| I-02 | 6일차 점검 | 중간 | 차트 기간 필터가 오전 9시 전에는 하루 전 날짜로 조회됨 | JavaScript `toISOString()` 이 UTC 기준 날짜를 돌려줌 | 브라우저의 한국 시간 기준으로 날짜 문자열을 만들도록 수정 (`_charts.html` 의 `period()`) | 화면에서 '최근 7일' 선택 후 요청 날짜 확인 |
| I-03 | 6일차 점검 | 낮음 | 상품 검색에 `%` 를 넣으면 모든 상품이 검색됨 | 검색어가 SQL LIKE 와일드카드로 해석됨 | `contains(q, autoescape=True)` 로 특수문자 이스케이프 | `test_pages_day6.py::test_product_search` |
| I-04 | CSV 업로드 구현 (2026-10-14) | 높음 | 같은 업로드 안에서 같은 키워드가 두 번 나오면 저장 중 오류(UNIQUE 위반)로 업로드 전체 실패 | 세션 설정 `autoflush=False` 라 방금 만든 키워드가 DB 조회에 보이지 않아 같은 단어를 또 만듦 | 아직 저장 전인 키워드 객체(`db.new`)를 먼저 찾아 재사용 (`database._save_keywords`) | `test_pages_upload.py` |
| I-05 | 업로드 이력 구현 (2026-10-15) | 중간 | `/products/uploads` 접속 시 422 오류 | `/products/{product_id}` 경로가 먼저 등록되어 'uploads' 를 상품 ID 로 해석 | 업로드 이력 경로를 상품 상세 경로보다 먼저 등록 | `test_pages_extra.py` (업로드 이력) |
| I-06 | 2026-10-14 | 낮음 | `docs/06_architecture.md` 에 Git 병합 충돌 표시(`<<<<<<<`, `>>>>>>>`)가 그대로 올라감 | 병합 충돌을 해결하지 않고 커밋 (1c57e76 병합) | 실제 반영 결과 기준으로 한 표로 정리 | 저장소 전체에서 충돌 표시 검색 0건 |
| I-07 | 2026-10-15 | 중간 | 설정에서 위험 키워드를 추가·삭제해도 대시보드·통계가 바뀌지 않음 | 키워드 목록만 바꾸고 이미 저장된 분석 결과는 '기존 리뷰 다시 분석' 버튼을 눌러야 갱신됨 (화면·API 모두) | 추가·수정·삭제 시 그 단어가 들어간 리뷰를 즉시 재분석 (`reanalyze_seller_reviews`) | `test_pages_day6.py`, `test_api_risk_keywords.py::test_keyword_change_applies_to_existing_reviews` |
| I-08 | 9일차 점검 (2026-10-15) | 높음 | 이메일 인증 코드를 5번 넘게 시도할 수 있음 | 코드 정보와 틀린 횟수를 브라우저 쿠키에 저장 → 발급 직후 쿠키로 되돌리면 횟수가 초기화됨. `SECRET_KEY` 가 예시 값이면 쿠키 속 해시로 코드를 알아낼 수도 있음 | 코드 정보를 서버 메모리에만 저장, 쿠키에는 남기지 않음 (`email_verify.py`) | `test_security_limits.py::test_old_cookie_replay_cannot_reset_tries`, `test_code_not_stored_in_cookie` |
| I-09 | 9일차 점검 | 높음 | 비밀번호 찾기 10분 잠금이 쿠키를 지우면 풀림 | 실패 횟수를 쿠키에 저장 | 이메일·IP 기준으로 서버에 기록 (`rate_limit.password_reset`) | `test_reset_lock_survives_cookie_clear` |
| I-10 | 9일차 점검 | 높음 | 로그인 실패 횟수 제한이 없어 비밀번호를 계속 대입할 수 있음 (30회 실패 후에도 로그인됨) | 로그인 시도 제한 미구현 | 같은 이메일 5회·같은 IP 20회 실패 시 10분 잠금. 화면과 API 공통 (`rate_limit.py`) | `test_login_locks_after_five_failures`, `test_api_login_shares_lock` |
| I-11 | 9일차 점검 | 높음 | REST API 회원가입은 이메일 인증 없이 가입됨 | 인증 확인을 화면 회원가입에만 넣음 | `POST /api/v1/auth/signup` 에 `email_code` 확인 추가 (`EMAIL_CODE_INVALID`) | `test_api_signup_requires_email_code` |
| I-12 | 9일차 점검 | 중간 | 인증 메일을 무제한으로 요청할 수 있음 (메일 폭탄·코드 재발급 반복) | 재발송 60초 대기만 있고 총 횟수 제한 없음 | 이메일당 1시간 5회, IP당 1시간 20회 | `test_send_limit_per_email`, `test_send_limit_per_ip` |
| I-13 | 9일차 점검 | 중간 | 3점 리뷰가 모두 '부정'으로 분류되어 중립이 0건, 부정 비율이 실제보다 높게 나옴 (데모 데이터 부정 비율 55% → 실제 27%) | 분석 규칙이 4점 이상만 긍정, 나머지는 모두 부정 | 위험 키워드 없는 3점 리뷰는 중립(NEU). 규칙 버전 `rule-v2`, 서버 시작 시 예전 결과 자동 재분석 | `test_unit.py`, `test_neutral_sentiment.py`, `test_api_stats.py::test_summary` |
| I-14 | 9일차 점검 | 중간 | 서명 키(`SECRET_KEY`)를 예시 값 그대로 써도 아무 경고가 없음 | 시작 시 점검 없음 | 비었거나 예시 값이면 서버 시작 시 경고 문구 출력 | `test_secret_key_warning` |
| I-15 | 9일차 점검 | 낮음 | 쓰지 않는 시안 `frontend/passwordreset_new.html` 이 저장소에 남아 있음 | 비밀번호 변경 화면을 Figma 기준 한 화면으로 바꾼 뒤 정리하지 않음 | 이번 커밋에서 `git rm frontend/passwordreset_new.html` 로 삭제 | 저장소 파일 목록 |
| I-16 | 9일차 점검 | 낮음 | `backend/tests/__pycache__/*.pyc` 14개가 저장소에 올라가 있음 | `.gitignore` 에 `__pycache__/` 를 넣기 전에 커밋되어 계속 추적됨 | `git rm -r --cached backend/tests/__pycache__` 로 추적 해제 (파일은 PC 에 남음) | `git ls-files \| grep pyc` 결과 0건 |

## 남은 위험 (알고 있지만 이번 범위에서 두는 것)

| 항목 | 내용 | 대응 |
|---|---|---|
| 시도 제한 기록이 서버 메모리에 있음 | 서버를 재시작하면 잠금·인증 코드가 초기화됨. 여러 프로세스로 실행하면 따로 셈 | 프로세스 1개로 운영 (`10_deployment.md`). 규모가 커지면 Redis 등 공유 저장소 |
| 이메일 기준 잠금 | 남의 이메일로 일부러 틀려서 그 사람의 로그인을 10분 막을 수 있음 | 잠금 시간을 짧게(10분) 유지. 운영 시 IP 기준 강화나 CAPTCHA 검토 |
| 분석이 규칙 기반 | 반어법·문맥은 판단하지 못함 | LLM·감성 모델 연동은 이번 범위 제외. `analyze_review()` 만 바꾸면 되도록 구조화 |
| 옛 API `POST /api/reviews` | `/api/v1` 과 별도로 남아 있는 리뷰 추가 API (화면에서 쓰지 않음) | 기존 URL 변경 금지 규칙에 따라 유지. 다음 버전에서 정리 |
