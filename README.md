# PIN POINT REVIEW (Pinpoint)

쇼핑몰 리뷰를 수집·정제·분석해서 셀러가 **불만이 숨어 있는 리뷰를 빠르게 찾고(위험 리뷰), 상품 문제와 배송·포장 문제를 나눠 보고, CS 답글까지 바로 처리**할 수 있게 돕는 대시보드 서비스입니다.

- **서비스 주소:** <https://semiproject01d-production.up.railway.app>
  - 회원가입 후 바로 사용할 수 있습니다 (배포 서버는 이메일 인증 단계 생략, 아래 [배포](#배포-railway) 참고)
  - 상태 확인: <https://semiproject01d-production.up.railway.app/api/v1/health> · API 문서: <https://semiproject01d-production.up.railway.app/docs>
- 목표 사용자: 네이버 스마트스토어·쿠팡 등 중소형 셀러, 자사몰 마케팅·CS 담당자
- 자세한 기획: [docs/01_project_overview.md](docs/01_project_overview.md) · 요구사항: [docs/02_requirements.md](docs/02_requirements.md)

## 역할 분담

| 이름 | 역할 | 담당 영역 |
|---|---|---|
| 정다은 | 팀장 / 백엔드·데이터 및 AI / 서버 오너 | 데이터베이스 설계, 백엔드 API 구현, 서버 배포 및 로직 처리 |
| 김서현 | 디자인 & 프론트엔드 오너 | UI/UX 디자인, 와이어프레임, 화면 퍼블리싱 및 프론트엔드 로직(HTML/CSS/JS), AI/외부 API 연동 |

## 주요 화면

| 화면 | 주소 | 내용 |
|---|---|---|
| 로그인 / 회원가입 | `/login`, `/signup` | 세션 쿠키 로그인(5회 실패 시 10분 잠금), 사업자번호·이메일 중복 확인, **이메일 인증 코드** |
| 비밀번호 변경하기 | `/password-reset` | 이름·이메일(인증 코드)·사업자 등록번호가 일치하면 새 비밀번호 설정 (5회 실패 시 10분 잠금) |
| 회원 탈퇴 완료 | `/withdrawn` | 탈퇴 직후 안내, 처음으로 돌아가기 |
| 대시보드 | `/dashboard` | **처리할 일**(미답변 위험 리뷰·최근 부정 리뷰·업로드), 위험 리뷰 건수, **급증한 부정 키워드**(v1.1), 최근 리뷰, 당월 방문자·구매자 |
| 상품 조회 | `/products` | **리뷰 CSV 업로드**(양식 내려받기, 새 위험 리뷰 안내·알림 메일), 상품 목록·검색, 평균 평점, 긍정/중립/부정/위험 리뷰 수 |
| 업로드 이력 | `/products/uploads` | CSV 업로드 기록 (추가·중복·오류 건수) |
| 리뷰 목록 | `/reviews` | 모든 상품의 리뷰를 상품·기간·감성·이슈·평점·답글 여부·블라인드·검색어로 찾기 |
| 상품 비교 | `/compare` | 두 상품의 평점·긍정/중립/부정 비율·이슈 유형·키워드 비교 |
| 상품별 대시보드 | `/products/{id}` | 상세 리뷰, **리뷰 블라인드·복구**, 월별 리뷰 추이 차트, 긍정·부정 요약 |
| 쇼핑몰 분석 | `/analysis` | 전월 대비 구매율, **월별 추이·긍/부정 비율·키워드 TOP 10 차트**, CSV 내보내기, AI 분석 리포트 |
| 리포트 (v1.1) | `/reports` | **주간·월간 리포트** (전기간 대비 지표, 감성·이슈·키워드·상품별·위험 리뷰), 'PDF로 저장'(브라우저 인쇄) |
| CS챗봇 | `/cschatbot` | 답글 없는 리뷰 + 추천 답글(내 **답글 템플릿** 적용) 수정·복사·처리 완료 |
| 설정 | `/settings` | 회원정보 수정·탈퇴, **위험 키워드 관리**(추가·삭제 즉시 기존 리뷰에 반영), 전체 리뷰 재분석, **알림 설정·답글 템플릿**(v1.1) |
| 의견 보내기 | `/feedback` | 서비스 의견 접수 |
| API 문서 | `/docs` | REST API(`/api/v1`) 전체 목록과 직접 호출 (Swagger UI) |
| 상태 확인 | `/api/v1/health` | 서버·DB 상태 JSON (로그인 불필요, 배포 후 확인용) |

## 문서

| 문서 | 내용 |
|---|---|
| [01_project_overview](docs/01_project_overview.md) | 기획 개요 |
| [02_requirements](docs/02_requirements.md) | 기능(FR-01\~31, v1.1 FR-28\~31 포함)·비기능(NFR-01\~11) 요구사항, User Story |
| [03_ui_design](docs/03_ui_design.md) | 화면 목록·흐름 |
| [04_database_design](docs/04_database_design.md) | 테이블·관계 |
| [05_api_spec](docs/05_api_spec.md) | REST API 명세 |
| [06_architecture](docs/06_architecture.md) | 구성·인증·데이터 흐름 |
| [07_test_plan](docs/07_test_plan.md) | 테스트 계획 |
| [08_issue_log](docs/08_issue_log.md) | 발견한 문제와 해결 기록 |
| [09_test_result](docs/09_test_result.md) | 테스트 결과 |
| [10_deployment](docs/10_deployment.md) | 배포 절차·체크리스트 |
| [11_final_report](docs/11_final_report.md) | 최종 보고서 |

## 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 백엔드 | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Uvicorn, Alembic(DB 마이그레이션, v1.1) |
| 데이터베이스 | MariaDB 10.5+ (utf8mb4, 배포는 MariaDB 11). 테스트는 임시 SQLite 파일 사용 |
| 화면 | Jinja2 템플릿(서버에서 HTML 생성) + JavaScript fetch + ECharts(차트) |
| 인증 | 세션 테이블 + HttpOnly 세션 쿠키, 비밀번호 PBKDF2 해시 |
| 분석 | 규칙 기반 감성(긍정·중립·부정)·위험도·이슈 유형·키워드 분석 (`analysis.py`, model_version `rule-v2`) |
| 테스트 | pytest, FastAPI TestClient, GitHub Actions(push·PR 마다 SQLite + MariaDB 11 자동 테스트, v1.1) |
| 배포 | Railway (웹 서비스 + MariaDB 11 Docker 컨테이너, HTTPS 자동) |

## 폴더 구조

```
semiproject_01_D/
├─ backend/                ← 실제 서버 (여기서 실행)
│  ├─ main.py              화면(HTML) 라우트
│  ├─ api_v1.py            REST API /api/v1/*
│  ├─ models.py            DB 테이블 (SQLAlchemy ORM, ERD 기준 15개 + v1.1 2개)
│  ├─ schemas.py           요청·응답 형식 (Pydantic)
│  ├─ analysis.py          리뷰 분석 규칙 · 키워드 추출 · 분석 리포트
│  ├─ reply_drafts.py      추천 답글 초안
│  ├─ auth.py / security.py 로그인 세션 · 비밀번호 해시
│  ├─ email_verify.py      이메일 인증 코드 (서버 메모리 저장)
│  ├─ rate_limit.py        로그인·비밀번호 찾기·인증 메일 시도 횟수 제한
│  ├─ database.py / db.py  DB 연결 · 테이블 생성 · 데모 데이터
│  ├─ pipeline.py          리뷰 데이터 적재·재분석 (내부 API)
│  ├─ alerts.py            (v1.1) 업로드 후 위험 리뷰 알림 메일
│  ├─ insights.py          (v1.1) 부정 키워드 급증 · 주간/월간 리포트 계산
│  ├─ alembic.ini, migrations/  (v1.1) DB 변경 이력 (Alembic)
│  ├─ templates/           실제로 화면에 쓰이는 HTML (Jinja2)
│  └─ tests/               자동 테스트 (pytest)
├─ frontend/               ← 디자인 시안 (정적 HTML, 서버에서 사용하지 않음)
├─ docs/                   기획·설계 문서
├─ .github/workflows/      (v1.1) 자동 테스트 (GitHub Actions)
└─ main.py                 최상위 폴더에서도 서버를 켤 수 있게 하는 실행 파일
```

> **frontend 와 backend/templates 의 관계**
> `frontend/` 는 디자이너가 만든 화면 시안이고, 실제 서비스 화면은 `backend/templates/` 입니다.
> 시안을 고쳤다면 같은 이름의 템플릿에도 반영해야 화면이 바뀝니다. (`productresearch.html` → `products.html`)

## 실행 방법 (Windows 기준)

```powershell
# 1) 가상환경 만들기 (처음 한 번)  ※ venv 폴더는 다른 PC 로 복사하지 말고 PC 마다 새로 만듭니다
cd semiproject_01_D
python -m venv venv
venv\Scripts\activate
pip install -r backend\requirements.txt

# 2) MariaDB 계정·DB 만들기 (처음 한 번)
#    backend\setup_mariadb.sql 의 '여기에_비밀번호' 를 바꿔 root 로 실행한 뒤, 파일은 다시 원래대로 되돌려 둡니다
mariadb -u root -p < backend\setup_mariadb.sql

# 3) 환경 설정 파일 만들기 (처음 한 번)
copy backend\.env.example backend\.env
#    backend\.env 의 DB_PASSWORD 에 2) 에서 정한 비밀번호 입력

# 4) 서버 실행 → http://127.0.0.1:8000
python -m uvicorn main:app --reload        # 최상위 폴더에서
#   또는 backend\run_server.bat 더블클릭
```

테이블은 서버를 처음 켤 때 자동으로 만들어지고, DB 가 비어 있으면 데모 데이터가 들어갑니다.

**DB 변경 이력 (Alembic, v1.1)** — 서버 자동 생성과 함께 쓸 수 있도록, 이미 있는 테이블은 건너뛰게 만들어 두었습니다.

```powershell
cd backend
python -m alembic upgrade head      # 처음 한 번: 버전 기록(alembic_version) 생성 + 새 테이블 추가
python -m alembic current           # 현재 버전 (0002 = v1.1)
# 모델(models.py)을 바꿨다면: python -m alembic revision --autogenerate -m "설명" → 파일 확인 → upgrade head
```

- **데모 계정** (로컬 개발용): `demo@pinpoint.kr` / `Pinpoint1!` — 배포 서버에서는 비밀번호를 바꿔 두었으므로 이 값으로 로그인되지 않습니다

## 이메일 인증 (회원가입 · 비밀번호 변경)

`backend/.env` 에 메일 서버를 설정하면 실제 메일로 6자리 인증 코드를 보냅니다.

```dotenv
# 비워 두면 '개발 모드': 메일 대신 화면과 서버 콘솔에 코드 표시
MAIL_HOST=smtp.gmail.com
MAIL_PORT=587
MAIL_USER=보내는메일@gmail.com
# Gmail 은 '앱 비밀번호' 사용 (2단계 인증 필요). 메일 발송 서비스(Brevo 등)의 SMTP 키도 가능
MAIL_PASSWORD=앱_비밀번호
MAIL_FROM=보내는메일@gmail.com
# 0 이면 인증 코드 확인을 끔 (시연·배포 서버)
EMAIL_VERIFICATION=1
```

> `.env` 는 값 뒤에 `#` 주석을 붙이면 주석까지 값으로 읽힙니다. 주석은 항상 따로 한 줄에 씁니다.

코드는 10분 유효, 재발송은 60초 뒤, 5번 틀리면 폐기됩니다. 같은 이메일로는 1시간에 5번, 같은 PC(IP)에서는 1시간에 20번까지 보낼 수 있습니다.
코드는 서버에만 저장되므로 서버를 다시 켜면 새로 받아야 합니다.

같은 메일 설정으로 **위험 리뷰 알림 메일**(v1.1)도 보냅니다. 설정 화면 '알림 설정'을 켠 셀러에게만, CSV 업로드에서 위험 리뷰가 새로 나왔을 때 응답을 먼저 보낸 뒤 발송합니다. `MAIL_HOST` 가 비어 있으면 메일 대신 서버 콘솔에 내용이 출력됩니다. REST API 회원가입(`POST /api/v1/auth/signup`)도 `email_code` 가 필요합니다.

**배포 서버에서는 꺼져 있습니다** (`EMAIL_VERIFICATION=0`). 사용 중인 배포 환경이 외부 메일 발송(SMTP)을 보장하지 않기 때문입니다. 기능 자체는 구현·테스트되어 있어, 메일 발송이 되는 서버에서는 `MAIL_*` 를 설정하고 `EMAIL_VERIFICATION=1` 로 바꾸면 코드 수정 없이 켜집니다. 로컬에서 `MAIL_HOST` 를 비워 두면 인증 흐름 전체를 개발 모드로 확인할 수 있습니다.

## 배포 (Railway)

```
[브라우저] --HTTPS--> [Railway 웹 서비스: uvicorn 1개 (Root Directory = backend)] --내부망--> [MariaDB 11 컨테이너 + 볼륨]
```

| 항목 | 값 |
|---|---|
| 서비스 주소 | <https://semiproject01d-production.up.railway.app> |
| 웹 서비스 Root Directory | `backend` |
| 시작 명령 | `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips '*'` |
| 상태 확인 경로 | `/api/v1/health` |
| 주요 환경 변수 | `DATABASE_URL`(`mariadb+pymysql://…@mariadb.railway.internal:3306/pinpoint`), `SECRET_KEY`, `COOKIE_SECURE=1`, `EMAIL_VERIFICATION=0`, `TZ=Asia/Seoul` |

- **업데이트:** `main` 에 push 하면 자동으로 다시 배포됩니다. 상태 확인을 통과해야 새 버전으로 바뀝니다.
- **프로세스는 1개**(`--workers 1`): 로그인 잠금·인증 코드 기록이 서버 메모리에 있기 때문입니다.
- **시간대:** `TZ=Asia/Seoul` 은 Railway 변수로 넣습니다 (`.env` 에 넣으면 적용되지 않음).
- **제한:** Railway 체험판(30일)을 사용합니다. 계속 운영하려면 유료 전환 또는 리눅스 서버로 옮깁니다.
- 처음부터 다시 배포하는 방법, 화면별 입력값, 배포 중 겪은 문제(I-31·I-32)는 [docs/10_deployment.md](docs/10_deployment.md) 에 있습니다.

## 휴대폰에서 보기

폭 768px 이하에서는 사이드바가 숨고 상단 ☰ 버튼으로 엽니다. 여러 칸 화면은 한 줄로 쌓입니다.
휴대폰 브라우저에서 <https://semiproject01d-production.up.railway.app> 로 바로 접속할 수 있습니다.

## 테스트

```powershell
pip install -r backend\requirements-dev.txt
cd backend
python -m pytest            # 전체 (또는 run_tests.bat)
python -m pytest -m pages   # 화면만  /  -m api : API만  /  -m unit : 단위
```

테스트는 임시 SQLite DB 를 사용하므로 실제 MariaDB 데이터는 건드리지 않습니다. GitHub 에 push·PR 하면 `.github/workflows/tests.yml` 이 SQLite 와 MariaDB 11 에서 같은 테스트를 자동으로 돌립니다 (저장소 **Actions** 탭에서 결과 확인). 자세한 내용: [backend/tests/README.md](backend/tests/README.md)

## 보안 규칙

- 실제 비밀번호·키는 **`backend/.env` 에만** 적습니다. `.env` 는 git 에 올라가지 않습니다(`.gitignore`).
- `setup_mariadb.sql`, `.env.example` 같은 공유 파일에는 실제 값을 적은 채로 커밋하지 않습니다.
- `backend/.env` 의 `SECRET_KEY` 는 길고 무작위인 값으로 바꿉니다. 예시 값 그대로면 서버를 켤 때 경고가 나옵니다.
  만드는 법: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- 로그인은 같은 이메일로 5번(같은 PC 에서 20번) 틀리면 10분 동안 잠깁니다. 시연 중 잠겼다면 서버를 다시 켜면 풀립니다.
  여러 사람이 같은 와이파이로 접속하는 발표라면 `.env` 의 `LOGIN_IP_MAX_FAILS`, `EMAIL_SEND_LIMIT_PER_IP` 를 늘리세요.
- 운영(`COOKIE_SECURE=1`)에서는 메일 서버(`MAIL_*`)를 설정하거나 `EMAIL_VERIFICATION=0` 으로 인증을 끕니다 (현재 배포 서버는 `0`). 메일 서버 없이 인증을 켜 두면 인증 코드를 화면에 보여 주지 않고 발송을 거부합니다.
- 배포 서버의 비밀 값(`SECRET_KEY`, DB 비밀번호)은 Railway 변수에만 저장하고, 데모 계정 비밀번호는 배포 직후 바꿉니다.
- 분석 CSV 내보내기는 `=`·`+`·`-`·`@` 로 시작하는 칸 앞에 `'` 를 붙여 엑셀에서 수식으로 실행되지 않게 합니다.

## Git 커밋 규칙

```
feat:     기능 추가          예) feat: 리뷰 블라인드 화면 추가
fix:      오류 수정          예) fix: 상품 검색 시 % 문자 오류 수정
docs:     문서 수정          예) docs: README 실행 방법 추가
test:     테스트 추가·수정   예) test: 블라인드 화면 테스트 추가
refactor: 동작은 같고 구조 개선
style:    화면 디자인·CSS
chore:    설정·기타 (.gitignore 등)
```

브랜치: 작은 수정은 `main` 에, 큰 작업은 `feature/기능명` 브랜치 → PR → 팀원 확인 후 합칩니다 (예: PR #1 `feature/day9-qa-fixes`). `main` 에 push 하면 배포 서버에 자동 반영되므로 커밋은 테스트가 통과한 상태에서 하고, 최종 버전은 `release: v1.0 프로젝트 최종 버전` 커밋과 `v1.0.0` 태그로 남깁니다 ([docs/10_deployment.md](docs/10_deployment.md)).
