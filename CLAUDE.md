# CLAUDE.md — PIN POINT REVIEW 프로젝트 규칙 (AI 코딩 에이전트용)

AI 에이전트(Claude Code 등)에게 작업을 맡길 때 이 파일을 먼저 읽게 합니다. 사람도 같은 규칙을 따릅니다.

## 프로젝트
- 쇼핑몰 셀러용 리뷰 분석 대시보드. 기획·요구사항은 `docs/01~02`, 설계는 `docs/03~06`
- 실제 서버는 `backend/`. `frontend/` 는 디자인 시안이며 서버에서 쓰지 않음 (화면 수정은 `backend/templates/`)

## 현재 개발 상태 (9일차, 2026-10-19)
- 기능 요구사항 FR-01~27, 비기능 NFR-01~11 구현 완료. 자동 테스트 347개 통과 (`docs/09_test_result.md`)
- 9일차 통합 점검 수정 I-26~I-30 반영 (입력 길이, 비밀번호 변경 시 다른 기기 로그아웃, CS챗봇 중복 방지, 로그아웃 POST 전용)
- 남은 일: 실제 MariaDB 에서 전체 테스트, 배포(`docs/10_deployment.md`), 발표·회고(`docs/11_final_report.md`)
- 분석은 규칙 기반(`analysis.py`, `rule-v2`). LLM·모델 학습은 이번 범위 제외

## 폴더 구조
```
backend/        실제 서버 — main.py(화면 라우트) · api_v1.py(REST /api/v1) · models.py · schemas.py · analysis.py
                pipeline.py(CSV 적재) · email_verify.py · rate_limit.py · templates/(화면) · tests/(pytest)
frontend/       디자인 시안 (서버에서 사용 안 함)
docs/           01~11 기획·설계·테스트·배포 문서
```

## 기술 스택 (임의 변경 금지)
- FastAPI + Pydantic v2 + SQLAlchemy 2.0 + MariaDB (테스트는 SQLite)
- 화면: Jinja2 템플릿 + Vanilla JavaScript(fetch) + ECharts. React 등 프레임워크 도입 금지
- 인증: sessions 테이블 + 세션 쿠키 (JWT 로 바꾸지 않음)

## 코드 위치
- 화면 라우트 `backend/main.py` · REST API `backend/api_v1.py` (`/api/v1`)
- 테이블 `backend/models.py` · 요청/응답 형식 `backend/schemas.py`
- 분석 규칙 `backend/analysis.py` · 추천 답글 `backend/reply_drafts.py`
- 이메일 인증 코드 `backend/email_verify.py` · 시도 횟수 제한 `backend/rate_limit.py` · CSV 적재 `backend/pipeline.py`
- 새 화면 템플릿은 `{% include '_layout_styles.html' %}` + `{% include '_sidebar.html' %}` 로 공통 스타일·모바일 메뉴 사용

## 반드시 지킬 것
- 셀러는 **자기 상품의 데이터만** 접근 (API 403 / 화면 404). 새 기능에도 소유권 검사 필수
- 통계·키워드·CSV 등 집계는 **`status = 'VISIBLE'` 리뷰만** (블라인드 제외)
- API 오류 응답은 `{code, message}` 형식
- 기존 API URL·DB 구조(테이블·컬럼) 임의 변경 금지. 필요하면 먼저 사람에게 확인
- 새 라이브러리 설치 전 확인. `requirements.txt` 에 버전과 함께 추가
- 비밀번호·키는 `backend/.env` 에만. 공유 파일(`setup_mariadb.sql`, `.env.example`)에 실제 값 금지
- 화면 입력 검증은 `schemas.py` 의 규칙(비밀번호·이메일)과 DB 컬럼 크기(`main.FIELD_MAX`)를 그대로 사용. 상태를 바꾸는 동작(로그아웃 등)은 GET 이 아닌 POST 로만
- 인증 코드·실패 횟수·잠금 같은 보안 상태는 쿠키(`request.session`)에 저장하지 않음 → `rate_limit.py`·`email_verify.py` 의 서버 저장소 사용
- 분석 규칙(`analysis.py`)을 바꾸면 `MODEL_VERSION` 을 올림 → 서버 시작 시 예전 결과 자동 재분석
- 문서는 `docs/01~11` 번호 체계 유지. 문제를 고치면 `docs/08_issue_log.md` 에 기록

## 테스트 방법
```
cd backend
python -m pytest            # 전체 (임시 SQLite, 실제 DB 는 건드리지 않음)
python -m pytest -m pages   # 화면만 / -m api : API 만 / -m unit : 단위
```
DB 는 `backend/models.py`(테이블 15개), API 규칙은 `docs/05_api_spec.md`, 화면은 `docs/03_ui_design.md` 참고

## Agent 에게 작업을 맡길 때 (일정표 19장: Context → Task → Constraints → Done Criteria → Test)
아래 형식으로 지시하고, 결과는 `docs/11_final_report.md` 부록 A 에 기록합니다.
```
Task:           (한 가지 작은 작업) 예) CSV 업로드 입력 검증을 개선한다
Context:        현재 상태·관련 파일  예) pipeline.py 의 ingest_rows, 업로드 화면 products.html
Constraints:    변경 허용 범위       예) DB 구조·API URL 변경 금지, 새 라이브러리 금지, 수정 파일은 pipeline.py·테스트만
Done Criteria:  완료조건 (번호로)    예) 1) 평점은 1~5 정수만  2) 미래 날짜 거부  3) 테스트 추가
Test:           확인 방법            예) 오류 행 안내 문구 확인, 정상 행은 그대로 추가, 전체 pytest 통과
```
Agent 는 작업 후 **변경한 파일 / 이유 / 실행한 테스트 / 기존 기능 영향**을 보고하고, 사람이 확인한 뒤 커밋합니다.

## 완료 기준 (Definition of Done, 일정표 21장)
기능 하나가 끝났다고 하려면 모두 체크되어야 합니다.
```
□ 요구사항 구현 (docs/02 의 FR·US 와 일치)   □ 실행 가능 (서버 기동, 화면에서 동작)
□ 오류 없음 (전체 pytest 통과)               □ 입력 검증 (잘못된 값은 안내하고 저장 안 함)
□ API 테스트 (tests/test_api_*.py)           □ UI 테스트 (tests/test_pages*.py)
□ 코드 Review (팀원 확인, 가능하면 PR)        □ Git Commit (규칙에 맞는 메시지)
□ 문서 반영 (docs·README, 문제였다면 08_issue_log)
```

## Git
- 커밋은 테스트가 통과한 상태에서만. 메시지는 `feat: / fix: / docs: / test: / refactor: / style: / chore:` + 한국어 설명
- 큰 작업이나 Agent 결과는 `feature/기능명` 브랜치 → PR → 팀원 확인 → `main` 에 합치기

## 작업 완료 조건
1. `cd backend && python -m pytest` 전부 통과 (새 기능은 테스트도 추가: 화면 `tests/test_pages*.py`, API `tests/test_api_*.py`)
2. 변경한 파일과 이유, 실행한 테스트를 보고
3. 커밋 메시지는 `feat: / fix: / docs: / test: / refactor: / style: / chore:` 형식 (README 참고)
