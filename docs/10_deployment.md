# 10. 배포 문서 — PIN POINT REVIEW

10일차(배포·발표·최종 검증) 산출물입니다. 배포 흐름은 일정표 기준 **Final Code → Test → Git → GitHub → Deploy → 서비스 확인** 입니다.

> 상태: **배포 전**. 배포를 마치면 6장의 표(주소·날짜·확인 결과)를 채웁니다.

## 1. 배포 구성

```
[사용자 브라우저] --HTTPS--> [nginx (443)] --HTTP--> [uvicorn 1개 프로세스 :8000 (FastAPI)] --> [MariaDB :3306]
                               인증서(Let's Encrypt)                      backend/.env 로 설정
```

| 항목 | 값 | 이유 |
|---|---|---|
| 서버 | Linux VM 1대 (예: Ubuntu 22.04 이상) | 화면·API·DB 를 한 서버에서 운영하는 소규모 서비스 |
| Python | 3.11 이상 | `README.md` 기술 스택 |
| DB | MariaDB 10.5 이상 (utf8mb4) | `backend/setup_mariadb.sql` 로 계정·DB 생성. 테이블은 서버 시작 시 자동 생성 |
| 앱 서버 | uvicorn **프로세스 1개** (`--workers 1`) | 로그인 잠금·인증 코드 기록이 서버 메모리에 있어 프로세스가 여러 개면 따로 셈 (`06_architecture.md` 4장) |
| 프록시 | nginx + HTTPS | 세션 쿠키를 `Secure` 로 보내기 위해 HTTPS 필수 (`COOKIE_SECURE=1`) |

## 2. 배포 전 확인 (Final Code → Test → Git)

- [x] `cd backend && python -m pytest` 전부 통과 (`09_test_result.md` 기록, 2026-10-19 347개 통과)
- [x] 공유 파일(`setup_mariadb.sql`, `.env.example`)에 실제 비밀번호 없음 (GitHub 기준 확인, 예시 값은 `여기에_비밀번호` 로 통일) · 커밋 전 `git status` 확인은 각자
- [x] 쓰지 않는 파일 정리 (`frontend/passwordreset_new.html`, 추적되던 `.pyc`, 쓰이지 않는 `FeedbackCreate` 삭제)
- [ ] 최종 커밋과 태그
  ```bash
  git commit -m "release: v1.0 프로젝트 최종 버전"
  git tag v1.0.0
  git push origin main --tags
  ```

## 3. 서버 준비 (처음 한 번)

```bash
# 1) 패키지
sudo apt update
sudo apt install -y python3 python3-venv mariadb-server nginx git

# 2) 코드 받기
sudo mkdir -p /srv/pinpoint && sudo chown $USER /srv/pinpoint
git clone https://github.com/jjddee0222-axfullstack01/semiproject_01_D.git /srv/pinpoint
cd /srv/pinpoint && git checkout v1.0.0

# 3) 가상환경
python3 -m venv venv
venv/bin/pip install -r backend/requirements.txt

# 4) DB 계정·DB 만들기
#    setup_mariadb.sql 을 복사해서 '여기에_비밀번호' 를 새 비밀번호로 바꾼 뒤 실행 (원본 파일은 고치지 않음)
cp backend/setup_mariadb.sql /tmp/setup.sql && nano /tmp/setup.sql
sudo mariadb < /tmp/setup.sql && rm /tmp/setup.sql
```

## 4. 환경 설정 (`backend/.env`)

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env          # 서버 사용자만 읽기
nano backend/.env
```

| 항목 | 운영 값 | 비고 |
|---|---|---|
| `DB_PASSWORD` | 3장에서 정한 비밀번호 | 개발 PC 와 다른 값 사용 |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` 결과 | 예시 값이면 시작 로그에 경고가 나옴 |
| `COOKIE_SECURE` | `1` | HTTPS 에서만 쿠키 전송 |
| `MAIL_HOST` 등 `MAIL_*` | 실제 SMTP (예: Gmail 은 앱 비밀번호) | 운영(`COOKIE_SECURE=1`)에서 비워 두면 인증 코드를 보낼 수 없어 회원가입·비밀번호 찾기가 막힘 (시작 로그에 경고) → 반드시 설정 |
| `LOGIN_IP_MAX_FAILS`, `EMAIL_SEND_LIMIT_PER_IP` | 비워 두면 20 | 발표장처럼 많은 사람이 같은 와이파이로 접속하면 100 정도로 늘림 |
| `EMAIL_VERIFICATION` | `1` | 운영에서는 인증 끄지 않음 |
| `INTERNAL_API_KEY` | 필요할 때만 긴 무작위 값 | 비워 두면 내부 API(`/api/v1/internal/*`) 전부 차단 |

## 5. 실행 (Deploy)

**systemd 서비스** `/etc/systemd/system/pinpoint.service`

```ini
[Unit]
Description=PIN POINT REVIEW
After=network.target mariadb.service

[Service]
User=www-data
WorkingDirectory=/srv/pinpoint
ExecStart=/srv/pinpoint/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always

[Install]
WantedBy=multi-user.target
```

- `--proxy-headers`: nginx 가 넘겨 준 실제 사용자 IP 를 사용 (이게 없으면 모든 사용자가 nginx 의 IP 로 보여 IP 기준 잠금이 서비스 전체를 막음)
- `www-data` 가 `/srv/pinpoint` 를 읽을 수 있게 권한 설정: `sudo chown -R www-data /srv/pinpoint`

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pinpoint
sudo journalctl -u pinpoint -n 30     # "[PIN POINT] DB: ..." 와 경고 문구가 없는지 확인
```

**nginx** `/etc/nginx/sites-available/pinpoint`

```nginx
server {
    server_name 도메인;
    client_max_body_size 6m;          # 리뷰 CSV 업로드 한도(5MB)보다 조금 크게

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/pinpoint /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d 도메인   # HTTPS 인증서
```

## 6. 서비스 확인 (최종 검증 기준)

일정표 10일차 최종 검증 기준과 확인 방법입니다. 배포 후 결과를 채웁니다.

| 기준 | 확인 방법 | 결과 |
|---|---|---|
| 프로그램 실행 가능 | `systemctl status pinpoint` 가 active, `curl https://도메인/api/v1/health` → `{"status":"ok","database":"ok",...}` | |
| 핵심 기능 정상 | `07_test_plan.md` 시나리오 S-01~S-12 를 배포 주소에서 실행 | |
| DB 연결 정상 | `/api/v1/health` 의 `"database": "ok"` (DB 가 꺼져 있으면 503), 시작 로그의 `[PIN POINT] DB: mariadb+pymysql://...` | |
| Frontend·Backend 연결 정상 | 쇼핑몰 분석 화면 차트 표시 (`/api/v1/stats/*` 호출 성공) | |
| 오류 처리 가능 | 없는 주소 → 404 화면, 남의 상품 → 404, 로그인 5회 실패 → 잠금 안내 | |
| README 존재 | 저장소 최상위 `README.md` | 있음 |
| Git History 존재 | `git log`, `v1.0.0` 태그 | |
| 발표 Demo 가능 | 데모 계정 또는 시연용 계정으로 시나리오 진행 | |

| 항목 | 값 |
|---|---|
| 서비스 주소 | |
| 배포 날짜 | |
| 배포 버전 | v1.0.0 |
| 확인한 사람 | |

## 7. 업데이트·되돌리기

```bash
cd /srv/pinpoint
git fetch --tags && git checkout v1.0.1        # 새 버전
venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart pinpoint                 # 재시작하면 로그인 잠금·인증 코드 기록은 초기화됨

git checkout v1.0.0 && sudo systemctl restart pinpoint   # 문제가 생기면 이전 태그로 되돌리기
```

분석 규칙(`MODEL_VERSION`)이 바뀐 버전이면 재시작할 때 예전 분석 결과가 자동으로 다시 분석됩니다 (로그: `리뷰 N건을 다시 분석했습니다`).

## 8. 백업

```bash
mariadb-dump -u root -p pinpoint > pinpoint_$(date +%Y%m%d).sql     # 매일 실행 권장 (cron)
```

