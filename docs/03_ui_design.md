# 03. UI 설계 — PIN POINT REVIEW

- Figma: https://www.figma.com/design/MHMdmt55vmKb10IicXSK1E/%EC%A0%9C%EB%AA%A9-%EC%97%86%EC%9D%8C?node-id=0-1&t=v7oITTnxlGeynka0-1
- 시안(정적 HTML): `frontend/` · 실제 서비스 화면: `backend/templates/` (시안을 고치면 템플릿에도 반영)

## 1. 화면 목록 (16개)

| # | 화면 | 시안 파일 → 실제 템플릿 | 주소 | 주요 요소 | 관련 요구사항 |
|---|---|---|---|---|---|
| 1 | 로그인 | index.html → index.html | `/login` | 이메일·비밀번호, 회원가입·비밀번호 찾기 링크 | US-02 |
| 2 | 회원가입 | joinmembership.html → joinmembership.html | `/signup` | 이름·이메일(+인증 코드)·비밀번호(규칙)·쇼핑몰명·플랫폼·사업자번호 | US-01, FR-21 |
| 3 | 비밀번호 변경하기 | passwordreset.html → passwordreset.html | `/password-reset` | (Figma) 이름·email(+인증 코드)·변경할 비밀번호·비밀번호 확인·사업자 등록 번호 한 화면, 규칙·일치 실시간 안내, 5회 실패 시 10분 잠금 | FR-20, FR-21 |
| 4 | 대시보드 | dashboard.html → dashboard.html | `/dashboard` | 처리할 일 카드 4개, 위험 리뷰 경고, 최근 리뷰 3개, 당월 방문자·구매자 | US-15, FR-24 |
| 5 | 상품 조회 | productresearch.html → products.html | `/products` | 리뷰 CSV 업로드(양식·업로드 이력·상품 비교 링크), 상품 검색, 상품 카드 | US-05, US-09 |
| 6 | 업로드 이력 | uploads.html → uploads.html | `/products/uploads` | 합계 4개(횟수·추가·중복·오류), 업로드별 표 | FR-23 |
| 7 | 상품별 대시보드 | productdashboard.html → productdashboard.html | `/products/{id}` | 상세 리뷰(필터·정렬·페이지·상세 모달) + 블라인드·복구, 월별 리뷰 추이 차트, 긍정·부정 요약 (감성 필터는 긍정·중립·부정) | US-05, US-06, US-12 |
| 8 | 리뷰 목록 | reviews.html → reviews.html | `/reviews` | 공개/블라인드 탭, 상품·기간·감성·이슈·평점·답글 여부·정렬·위험만·검색어 필터, 20개씩 페이지 | FR-22 |
| 9 | 쇼핑몰 분석 | analysis.html → analysis.html | `/analysis` | 지표 4개, 리뷰 통계 차트 4개, CSV 내보내기, 상품 비교 링크, AI 분석 리포트, 칭찬·불만 리뷰, 운영 특이 사항 | US-12~14 |
| 10 | 상품 비교 | compare.html → compare.html | `/compare` | 두 상품 선택, 차이 요약 문장, 평점·리뷰 수·위험 리뷰, 긍정·중립·부정 비율 막대, 이슈 유형, 키워드 TOP 5 | FR-15, US-17 |
| 11 | CS챗봇 | cschatbot.html → cschatbot.html | `/cschatbot` | 답글 없는 리뷰(위험도순) + 추천 답글 수정·복사·처리 완료·되돌리기 | US-07, US-15, US-16 |
| 12 | 설정 | informationedit.html → informationedit.html | `/settings` | 회원정보 수정·탈퇴, 위험 키워드 관리(추가·삭제 즉시 반영)·전체 재분석 | US-04, FR-18, FR-27 |
| 13 | 회원 탈퇴 완료 | withdrawn.html → withdrawn.html | `/withdrawn` | (Figma) '회원 탈퇴가 완료되었습니다.' + 처음으로 돌아가기 (탈퇴 직후 한 번만 표시) | US-04 |
| 14 | 의견 보내기 | sendfeedback.html → sendfeedback.html | `/feedback` | 불편 사항·제안 입력 | - |
| 15 | 404 | 404page.html → 404page.html | 없는 주소 | 안내 문구, 처음으로 돌아가기 | 예외 화면 |
| 16 | (공통) 모바일 메뉴 | - → _sidebar.html | 모든 사이드바 화면 | 768px 이하: 상단 바 + ☰ 버튼으로 사이드바 열기·닫기, 여러 칸 화면은 한 줄로 | FR-25 |

공통: 왼쪽 사이드바(대시보드·상품 조회·리뷰 목록·분석·CS챗봇 / 설정·의견 보내기·로그아웃), 상단 안내 메시지(성공=초록, 오류=빨강).
Figma 프레임 13개 중 11개는 기존 화면, 2개(비밀번호 변경하기, 회원 탈퇴 완료)는 추가로 구현. Figma 에 없는 리뷰 목록·업로드 이력·상품 비교는 기존 화면과 같은 스타일로 만듦.

## 2. 화면 흐름

```
로그인 ─┬─ 회원가입 (이메일 인증) → 로그인
        ├─ 비밀번호 변경하기 (이메일 인증) → 로그인
        └─ 대시보드 ─┬─ 처리할 일 → CS챗봇 / 리뷰 목록 / 상품 조회
                     ├─ 상품 조회 ─┬─ 상품별 대시보드 (블라인드·복구)
                     │             ├─ 업로드 이력
                     │             └─ 상품 비교
                     ├─ 리뷰 목록 → 상품별 대시보드 / CS챗봇
                     ├─ 쇼핑몰 분석 → 상품 비교 / CS챗봇
                     ├─ CS챗봇 → 상품 바로가기 → 상품별 대시보드
                     ├─ 설정 ─┬─ 위험 키워드 → 재분석
                     │        └─ 회원 탈퇴 → 탈퇴 완료 → 처음으로
                     └─ 의견 보내기
```

## 3. 상태별 화면 (예외 화면)

| 상황 | 표시 |
|---|---|
| 로그인 안 함 | 로그인 화면으로 이동 + "로그인이 필요합니다." |
| 데이터 없음 | 리뷰·상품·검색 결과·차트마다 "…이 없습니다" 문구 |
| 남의 상품·리뷰 주소 | 404 화면 (존재 여부를 알려 주지 않음) |
| 입력 오류 | 같은 화면에 빨간 안내 + 입력값 유지 |
| 차트 로딩 / 실패 | "불러오는 중…" / "통계를 불러오지 못했습니다." / 차트 라이브러리를 못 불러오면 같은 데이터를 표로 표시 |
| 되돌릴 수 있는 작업 | 블라인드 → '복구', CS챗봇 처리 완료 → '되돌리기' |

## 4. 차트 규칙

- 데이터는 같은 서버의 REST API(`/api/v1/stats/*`)를 fetch 로 불러와 ECharts 로 그림
- 긍정 = 파랑, 부정 = 빨강, 중립 = 회색 (색약 사용자도 구분되는 조합. 범례·숫자 라벨 함께 표시)
- 리뷰 수와 평균 평점은 단위가 달라 **차트를 따로** 그림 (한 차트에 축 두 개를 쓰지 않음)

## 5. 화면별 호출 API (Frontend → Backend)

화면은 서버(Jinja2)가 HTML 을 만들어 보내는 방식이라, 대부분은 **폼 전송(POST) → 서버 처리 → 화면 다시 그리기**로 동작합니다. 차트·상세 보기·인증 코드처럼 화면을 새로 고치지 않아야 하는 부분만 JavaScript `fetch` 로 REST API 를 부릅니다.

| 화면 | 화면을 여는 주소 | 폼 전송 (화면 라우트, `main.py`) | fetch 로 부르는 API (JSON) |
|---|---|---|---|
| 로그인 | `GET /login` | `POST /login` | - |
| 회원가입 | `GET /signup` | `POST /signup` | `POST /email-code` (인증 코드 받기) |
| 비밀번호 변경하기 | `GET /password-reset` | `POST /password-reset` | `POST /email-code` |
| 대시보드 | `GET /dashboard` | - | - |
| 상품 조회 | `GET /products?q=` | `POST /products/upload` (CSV) · `GET /products/upload-template.csv` (양식) | - |
| 업로드 이력 | `GET /products/uploads` | - | - |
| 상품별 대시보드 | `GET /products/{id}?필터` | `POST /reviews/{id}/blind` · `POST /reviews/{id}/restore` | `GET /api/v1/reviews/{id}` (상세 모달) · `GET /api/v1/stats/monthly-trend?product_id=` (차트) |
| 리뷰 목록 | `GET /reviews?필터` | - | - |
| 쇼핑몰 분석 | `GET /analysis` | - | `GET /api/v1/stats/monthly-trend` · `/stats/sentiment-ratio` · `/stats/keywords/top` (차트 4개) · `GET /api/v1/exports/stats.csv` · `/exports/reviews.csv` (내려받기 링크) |
| 상품 비교 | `GET /compare?a=&b=` | - | - |
| CS챗봇 | `GET /cschatbot` | `POST /cschatbot/done` (처리 완료) · `POST /cschatbot/undo/{reply_id}` (되돌리기) | - |
| 설정 | `GET /settings` | `POST /settings` (비밀번호 변경 시 '확인' 칸 필수, 다른 기기 로그인 종료) · `POST /settings/risk-keywords` · `POST /settings/risk-keywords/{id}/delete` · `POST /settings/reanalyze` · `POST /withdraw` | - |
| 회원 탈퇴 완료 | `GET /withdrawn` | - | - |
| 의견 보내기 | `GET /feedback` | `POST /feedback` | - |
| 공통 (사이드바) | - | `POST /logout` (로그아웃 버튼. `GET /logout` 은 로그아웃하지 않고 대시보드로 이동) | - |

화면 라우트와 REST API 는 같은 세션 쿠키(`session_id`)를 쓰므로, fetch 호출에도 로그인 정보가 자동으로 함께 갑니다. 같은 기능을 외부 프로그램에서 쓰려면 REST API(`/api/v1`, [05_api_spec.md](05_api_spec.md))를 사용합니다.

