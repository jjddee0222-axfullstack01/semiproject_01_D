# 08. 이슈 로그 — PIN POINT REVIEW

개발·점검 중 발견한 문제와 원인, 해결 방법입니다.

- **심각도**: 높음(보안·데이터 손상·핵심 기능 불가) / 중간(기능이 기대와 다르게 동작) / 낮음(표시·문서)
- **확인**: 문제를 재현하고, 고친 뒤 통과하는 테스트

## 요약

| 구분 | 건수 | 상태 |
|---|---|---|
| 높음 | 6 | 모두 해결 |
| 중간 | 15 | 모두 해결 |
| 낮음 | 12 | 모두 해결 |

## 이슈 목록

| ID | 발견 시점 | 심각도 | 문제 | 원인 | 해결 | 확인 |
|---|---|---|---|---|---|---|
| I-01 | 6일차 점검 | 높음 | 공유 파일 `backend/setup_mariadb.sql` 에 실제 DB 비밀번호가 들어간 채 커밋됨 | 비밀 값과 공유 양식 파일의 구분이 없었음 | 예시 값(`여기에_비밀번호`)으로 바꾸고 실제 값은 `backend/.env` 에만 두도록 규칙화 (`README` 보안 규칙, `CLAUDE.md`), `.gitignore` 정리 (커밋 9814255, 2026-10-14) | 커밋 전 `git diff` 확인. **Git 기록에는 예전 값이 남아 있으므로 DB 비밀번호는 새 값으로 바꿔 사용** |
| I-02 | 6일차 점검 | 중간 | 차트 기간 필터가 오전 9시 전에는 하루 전 날짜로 조회됨 | JavaScript `toISOString()` 이 UTC 기준 날짜를 돌려줌 | 브라우저의 한국 시간 기준으로 날짜 문자열을 만들도록 수정 (`_charts.html` 의 `period()`) | 화면에서 '최근 7일' 선택 후 요청 날짜 확인 |
| I-03 | 6일차 점검 | 낮음 | 상품 검색에 `%` 를 넣으면 모든 상품이 검색됨 | 검색어가 SQL LIKE 와일드카드로 해석됨 | `contains(q, autoescape=True)` 로 특수문자 이스케이프 | `test_pages_day6.py::test_product_search` |
| I-04 | CSV 업로드 구현 (2026-10-14) | 높음 | 같은 업로드 안에서 같은 키워드가 두 번 나오면 저장 중 오류(UNIQUE 위반)로 업로드 전체 실패 | 세션 설정 `autoflush=False` 라 방금 만든 키워드가 DB 조회에 보이지 않아 같은 단어를 또 만듦 | 아직 저장 전인 키워드 객체(`db.new`)를 먼저 찾아 재사용 (`database._save_keywords`) | `test_pages_upload.py` |
| I-05 | 업로드 이력 구현 (2026-10-15) | 중간 | `/products/uploads` 접속 시 422 오류 | `/products/{product_id}` 경로가 먼저 등록되어 'uploads' 를 상품 ID 로 해석 | 업로드 이력 경로를 상품 상세 경로보다 먼저 등록 | `test_pages_extra.py` (업로드 이력) |
| I-06 | 2026-10-14 | 낮음 | `docs/06_architecture.md` 에 Git 병합 충돌 표시(`<<<<<<<`, `>>>>>>>`)가 그대로 올라감 | 병합 충돌을 해결하지 않고 커밋 (1c57e76 병합) | 실제 반영 결과 기준으로 한 표로 정리 | 저장소 전체에서 충돌 표시 검색 0건 |
| I-07 | 2026-10-15 | 중간 | 설정에서 위험 키워드를 추가·삭제해도 대시보드·통계가 바뀌지 않음 | 키워드 목록만 바꾸고 이미 저장된 분석 결과는 '기존 리뷰 다시 분석' 버튼을 눌러야 갱신됨 (화면·API 모두) | 추가·수정·삭제 시 그 단어가 들어간 리뷰를 즉시 재분석 (`reanalyze_seller_reviews`) | `test_pages_day6.py`, `test_api_risk_keywords.py::test_keyword_change_applies_to_existing_reviews` |
| I-08 | 7일차 점검 (2026-10-15) | 높음 | 이메일 인증 코드를 5번 넘게 시도할 수 있음 | 코드 정보와 틀린 횟수를 브라우저 쿠키에 저장 → 발급 직후 쿠키로 되돌리면 횟수가 초기화됨. `SECRET_KEY` 가 예시 값이면 쿠키 속 해시로 코드를 알아낼 수도 있음 | 코드 정보를 서버 메모리에만 저장, 쿠키에는 남기지 않음 (`email_verify.py`) | `test_security_limits.py::test_old_cookie_replay_cannot_reset_tries`, `test_code_not_stored_in_cookie` |
| I-09 | 7일차 점검 | 높음 | 비밀번호 찾기 10분 잠금이 쿠키를 지우면 풀림 | 실패 횟수를 쿠키에 저장 | 이메일·IP 기준으로 서버에 기록 (`rate_limit.password_reset`) | `test_reset_lock_survives_cookie_clear` |
| I-10 | 7일차 점검 | 높음 | 로그인 실패 횟수 제한이 없어 비밀번호를 계속 대입할 수 있음 (30회 실패 후에도 로그인됨) | 로그인 시도 제한 미구현 | 같은 이메일 5회·같은 IP 20회 실패 시 10분 잠금. 화면과 API 공통 (`rate_limit.py`) | `test_login_locks_after_five_failures`, `test_api_login_shares_lock` |
| I-11 | 7일차 점검 | 높음 | REST API 회원가입은 이메일 인증 없이 가입됨 | 인증 확인을 화면 회원가입에만 넣음 | `POST /api/v1/auth/signup` 에 `email_code` 확인 추가 (`EMAIL_CODE_INVALID`) | `test_api_signup_requires_email_code` |
| I-12 | 7일차 점검 | 중간 | 인증 메일을 무제한으로 요청할 수 있음 (메일 폭탄·코드 재발급 반복) | 재발송 60초 대기만 있고 총 횟수 제한 없음 | 이메일당 1시간 5회, IP당 1시간 20회 | `test_send_limit_per_email`, `test_send_limit_per_ip` |
| I-13 | 7일차 점검 | 중간 | 3점 리뷰가 모두 '부정'으로 분류되어 중립이 0건, 부정 비율이 실제보다 높게 나옴 (데모 데이터 부정 비율 55% → 실제 27%) | 분석 규칙이 4점 이상만 긍정, 나머지는 모두 부정 | 위험 키워드 없는 3점 리뷰는 중립(NEU). 규칙 버전 `rule-v2`, 서버 시작 시 예전 결과 자동 재분석 | `test_unit.py`, `test_neutral_sentiment.py`, `test_api_stats.py::test_summary` |
| I-14 | 7일차 점검 | 중간 | 서명 키(`SECRET_KEY`)를 예시 값 그대로 써도 아무 경고가 없음 | 시작 시 점검 없음 | 비었거나 예시 값이면 서버 시작 시 경고 문구 출력 | `test_secret_key_warning` |
| I-15 | 7일차 점검 | 낮음 | 쓰지 않는 시안 `frontend/passwordreset_new.html` 이 저장소에 남아 있음 | 비밀번호 변경 화면을 Figma 기준 한 화면으로 바꾼 뒤 정리하지 않음 | 이번 커밋에서 `git rm frontend/passwordreset_new.html` 로 삭제 | 저장소 파일 목록 |
| I-16 | 7일차 점검 | 낮음 | `backend/tests/__pycache__/*.pyc` 14개가 저장소에 올라가 있음 | `.gitignore` 에 `__pycache__/` 를 넣기 전에 커밋되어 계속 추적됨 | `git rm -r --cached backend/tests/__pycache__` 로 추적 해제 (파일은 PC 에 남음) | `git ls-files \| grep pyc` 결과 0건 |
| I-17 | 7일차 2차 점검 (2026-10-15) | 중간 | 리뷰 CSV 내보내기에 엑셀 수식이 그대로 들어감. 본문이 `=HYPERLINK("http://...","클릭")` 이면 엑셀에서 열 때 링크·수식으로 동작 (CSV 수식 주입) | 고객이 쓴 리뷰 본문·작성자명을 그대로 CSV 칸에 씀 | `=`, `+`, `-`, `@` 로 시작하는 글자 칸 앞에 `'` 를 붙여 글자로 취급 (`api_v1.csv_safe`) | `test_review_fixes.py::test_review_export_neutralizes_formula`, `test_csv_safe` |
| I-18 | 7일차 2차 점검 | 중간 | 메일 서버 없이 HTTPS 운영 설정(`COOKIE_SECURE=1`)으로 배포하면 인증 코드가 화면에 표시됨 → 공개 정보(이름·이메일·사업자 번호)만으로 남의 비밀번호 변경 가능, 가입 여부도 드러남 | `MAIL_HOST` 가 없으면 운영 여부와 관계없이 개발 모드로 동작 | 운영 설정에서는 코드를 화면에 보여 주지 않고 503 "메일 서버 미설정" 안내, 서버 시작 시 경고 (`email_verify.production_mode`) | `test_production_without_mail_server_refuses`, `test_production_with_mail_server_sends`, `test_local_dev_mode_still_shows_code` |
| I-19 | 7일차 2차 점검 | 중간 | 발표장·강의실처럼 같은 와이파이(같은 IP)를 쓰는 여러 사람이 접속하면 IP 기준 제한(로그인 실패 20회, 인증 메일 20회/시간)에 함께 걸려 모두 막힐 수 있음 | 제한 값이 코드에 고정 | `.env` 의 `LOGIN_MAX_FAILS`, `LOGIN_LOCK_MINUTES`, `LOGIN_IP_MAX_FAILS`, `EMAIL_SEND_LIMIT_PER_EMAIL`, `EMAIL_SEND_LIMIT_PER_IP` 로 조정 가능 (`rate_limit.env_int`) | `test_env_int` |
| I-20 | 7일차 2차 점검 | 낮음 | `/products/abc` 는 404 화면 대신 JSON 오류(422), `/products/99999999999999999999` 는 서버 오류(500) | 경로 값 검증 오류와 정수 범위 초과를 화면용으로 처리하지 않음 | 화면은 404 화면, API 는 `{code: NOT_FOUND}` 404 (API 의 형식 오류 응답은 그대로) | `test_bad_product_path_shows_404_page`, `test_bad_product_id_in_api` |
| I-21 | 7일차 2차 점검 | 낮음 | 중립 도입 후에도 분석 화면 차트 제목이 "긍정 / 부정 비율", 리뷰 목록 필터가 "긍정·부정 전체" | 문구 미갱신 | "긍정 / 중립 / 부정 비율", "감성 전체" | `test_three_way_sentiment_wording` |
| I-22 | 7일차 2차 점검 | 낮음 | 차트 툴팁·대체 표에 키워드 이름이 HTML 로 들어감 (셀러 본인 화면에만 영향) | 문자열을 그대로 HTML 에 삽입 | HTML 특수문자 이스케이프 (`_charts.html` 의 `esc`) | 코드 검토 |
| I-23 | 7일차 2차 점검 | 낮음 | 테스트를 돌릴 때마다 `SECRET_KEY` 경고가 출력됨, 문서의 테스트 수(298)가 실제와 다름 | 테스트용 키가 경고 목록의 값, favicon 테스트 추가 후 미갱신 | 테스트용 키 변경, `09_test_result.md`·`11_final_report.md` 갱신 | 테스트 출력에 경고 없음 |
| I-24 | 8일차 Agent Task (2026-10-16) | 중간 | CSV 업로드에서 평점 `4.5` 는 4점으로 잘려 저장, 미래 작성일(`2099-01-01`)도 저장, 255자 넘는 상품명은 잘려 저장되어 다시 올리면 같은 상품이 중복 생성될 수 있음, 아주 긴 본문은 MariaDB TEXT(65,535바이트) 한도를 넘을 수 있음 | 값 검증 없이 잘라서 저장 | 잘라 저장하지 않고 오류 행으로 안내 (`pipeline._row_problem`): "평점은 1~5 정수", "작성일이 미래", "상품명 255자 초과", "리뷰내용이 너무 김" — Agent Task T-8-1 (`11_final_report.md` 부록 A) | `test_agent_task_day8.py` |
| I-25 | 8일차 정적 점검 | 낮음 | 쓰이지 않는 코드 `schemas.FeedbackCreate` | 의견 보내기를 화면 폼으로만 구현하면서 남음 | 삭제 (`09_test_result.md` 5장 정적 점검) | 전체 테스트 통과 |
| I-26 | 9일차 통합 점검 (2026-10-19) | 중간 | 화면 회원가입에서 이름 51자·쇼핑몰 이름 101자·이메일 256자 이상, 설정 화면에서 쇼핑몰 이름 101자 이상을 넣으면 MariaDB 에서 저장 오류(500). 비밀번호 규칙도 화면은 "8자 이상", API 는 "8~64자"로 달랐음 | 화면 라우트가 DB 컬럼 크기를 검사하지 않음 (테스트는 SQLite 라 긴 값도 저장되어 드러나지 않음), 화면과 API 가 규칙을 따로 정의 | DB 컬럼 크기와 같은 길이 검사(`main.too_long`), 화면도 `schemas.py` 의 비밀번호·이메일 규칙을 그대로 사용, 입력칸 `maxlength` | `test_day9_fixes.py::test_signup_rejects_too_long`, `test_settings_rejects_too_long_mall_name`, `test_screen_password_rule_matches_api` |
| I-27 | 9일차 통합 점검 | 중간 | 설정 화면이나 `PATCH /api/v1/users/me/password` 로 비밀번호를 바꿔도 다른 기기의 로그인이 최대 7일간 유지됨 (비밀번호 찾기는 모든 기기 로그아웃) | 비밀번호 변경 경로마다 세션 처리 규칙이 달랐음 | 지금 쓰는 세션만 남기고 나머지 삭제 (`auth.end_other_sessions`), 화면·API 공통 | `test_settings_password_change_ends_other_sessions`, `test_api_password_change_ends_other_sessions` |
| I-28 | 9일차 통합 점검 | 낮음 | 설정 화면에 '비밀번호 확인' 칸이 없어 오타가 나면 그대로 그 비밀번호로 바뀜 | 확인 입력 없음 | '변경할 비밀번호 확인' 칸 추가, 두 값이 다르면 저장하지 않음 | `test_settings_password_confirm_mismatch` |
| I-29 | 9일차 통합 점검 | 중간 | CS챗봇에서 '처리 완료'를 두 번 누르거나 뒤로 가기 후 다시 제출하면 같은 답글이 중복 저장됨 | 이미 답글이 있는지 확인하지 않음 | 이미 답글이 있는 리뷰면 "이미 처리 완료된 리뷰입니다" 안내 후 저장하지 않음 | `test_cschatbot_done_twice_saves_once` |
| I-30 | 9일차 통합 점검 | 낮음 | 사이드바 로그아웃이 GET 링크라서, 다른 사이트가 `<img src=".../logout">` 같은 방법으로 사용자를 몰래 로그아웃시킬 수 있음 | 상태를 바꾸는 동작을 GET 으로 허용 | 로그아웃은 POST 로만 (사이드바는 폼 버튼). `GET /logout` 은 로그아웃하지 않고 대시보드(비로그인이면 로그인 화면)로 이동 | `test_get_logout_does_not_log_out`, `test_post_logout_logs_out`, `test_sidebar_logout_is_post_form` |
| I-31 | 10일차 배포 (2026-10-20) | 중간 | Railway 첫 배포에서 서버가 `uvicorn: command not found` 로 시작되지 않음 | `requirements.txt` 가 저장소 최상위가 아니라 `backend/` 안에 있어, 빌드 단계에서 패키지 설치가 건너뛰어짐 | 웹 서비스 Settings 의 Root Directory 를 `backend` 로 지정 (`10_deployment.md` 5장) | 빌드 로그에 패키지 설치 기록, 서버 시작 로그 `Application startup complete` |
| I-32 | 10일차 배포 | 중간 | 서버 시작 시 `[DB 연결 실패] ... @:3306` — DB 주소의 호스트가 비어 `localhost` 로 접속을 시도함 | `DATABASE_URL` 의 `${{MariaDB.RAILWAY_PRIVATE_DOMAIN}}` 참조가 서비스 이름과 맞지 않아 빈 값으로 바뀜 | MariaDB 서비스의 Private Networking 주소(`mariadb.railway.internal`)를 직접 입력 (`10_deployment.md` 4장) | 시작 로그 `[PIN POINT] DB: mariadb+pymysql://pinpoint:***@mariadb.railway.internal:3306/...`, `/api/v1/health` → `database: ok` |
| I-33 | 10일차 MariaDB 전체 테스트 (2026-10-21) | 낮음 | 테스트를 실제 MariaDB(`TEST_DATABASE_URL`)로 돌리면 347개 중 11개 실패. 배포 서버는 모든 기능 정상 | **테스트 코드의 DB 차이**: ① 테스트가 확인용으로 여는 세션이 MariaDB 기본 격리 수준(REPEATABLE READ) 때문에 화면 요청이 저장한 값을 못 봄(8건) ② MariaDB 는 CHECK 제약 위반을 `IntegrityError` 가 아니라 `OperationalError`(4025)로 알림(3건, 저장 거부 자체는 정상) ③ 범위를 넘는 ID 의 오류 코드가 SQLite 와 다름(1건, 둘 다 404). 서버 코드는 요청마다 새 세션을 쓰므로 영향 없음 | 테스트 세션을 READ COMMITTED 로 열고(`conftest.session`), 제약 위반은 두 예외 모두 허용, ID 범위 초과는 두 오류 코드 모두 허용. 서버 코드 변경 없음 | MariaDB·SQLite 양쪽에서 전체 pytest |

## 남은 위험 (알고 있지만 이번 범위에서 두는 것)

| 항목 | 내용 | 대응 |
|---|---|---|
| 시도 제한 기록이 서버 메모리에 있음 | 서버를 재시작하면 잠금·인증 코드가 초기화됨. 여러 프로세스로 실행하면 따로 셈 | 프로세스 1개로 운영 (`10_deployment.md`). 규모가 커지면 Redis 등 공유 저장소 |
| 이메일 기준 잠금 | 남의 이메일로 일부러 틀려서 그 사람의 로그인을 10분 막을 수 있음 | 잠금 시간을 짧게(10분) 유지. 운영 시 IP 기준 강화나 CAPTCHA 검토 |
| 분석이 규칙 기반 | 반어법·문맥은 판단하지 못함 | LLM·감성 모델 연동은 이번 범위 제외. `analyze_review()` 만 바꾸면 되도록 구조화 |
| 옛 API `POST /api/reviews` | `/api/v1` 과 별도로 남아 있는 리뷰 추가 API (화면에서 쓰지 않음) | 기존 URL 변경 금지 규칙에 따라 유지. 다음 버전에서 정리 |
