# CLAUDE.md — PIN POINT REVIEW 프로젝트 규칙 (AI 코딩 에이전트용)

AI 에이전트(Claude Code 등)에게 작업을 맡길 때 이 파일을 먼저 읽게 합니다. 사람도 같은 규칙을 따릅니다.

## 프로젝트
- 쇼핑몰 셀러용 리뷰 분석 대시보드. 기획·요구사항은 `docs/01~02`, 설계는 `docs/03~06`
- 실제 서버는 `backend/`. `frontend/` 는 디자인 시안이며 서버에서 쓰지 않음 (화면 수정은 `backend/templates/`)

## 기술 스택 (임의 변경 금지)
- FastAPI + Pydantic v2 + SQLAlchemy 2.0 + MariaDB (테스트는 SQLite)
- 화면: Jinja2 템플릿 + Vanilla JavaScript(fetch) + ECharts. React 등 프레임워크 도입 금지
- 인증: sessions 테이블 + 세션 쿠키 (JWT 로 바꾸지 않음)

## 코드 위치
- 화면 라우트 `backend/main.py` · REST API `backend/api_v1.py` (`/api/v1`)
- 테이블 `backend/models.py` · 요청/응답 형식 `backend/schemas.py`
- 분석 규칙 `backend/analysis.py` · 추천 답글 `backend/reply_drafts.py`
- 이메일 인증 코드 `backend/email_verify.py` · CSV 적재 `backend/pipeline.py`
- 새 화면 템플릿은 `{% include '_layout_styles.html' %}` + `{% include '_sidebar.html' %}` 로 공통 스타일·모바일 메뉴 사용

## 반드시 지킬 것
- 셀러는 **자기 상품의 데이터만** 접근 (API 403 / 화면 404). 새 기능에도 소유권 검사 필수
- 통계·키워드·CSV 등 집계는 **`status = 'VISIBLE'` 리뷰만** (블라인드 제외)
- API 오류 응답은 `{code, message}` 형식
- 기존 API URL·DB 구조(테이블·컬럼) 임의 변경 금지. 필요하면 먼저 사람에게 확인
- 새 라이브러리 설치 전 확인. `requirements.txt` 에 버전과 함께 추가
- 비밀번호·키는 `backend/.env` 에만. 공유 파일(`setup_mariadb.sql`, `.env.example`)에 실제 값 금지

## 작업 완료 조건
1. `cd backend && python -m pytest` 전부 통과 (새 기능은 테스트도 추가: 화면 `tests/test_pages*.py`, API `tests/test_api_*.py`)
2. 변경한 파일과 이유, 실행한 테스트를 보고
3. 커밋 메시지는 `feat: / fix: / docs: / test: / refactor: / style: / chore:` 형식 (README 참고)
