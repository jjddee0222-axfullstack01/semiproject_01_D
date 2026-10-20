# 10. 배포 문서 — PIN POINT REVIEW

10일차(배포·발표·최종 검증) 산출물입니다. 배포 흐름은 일정표 기준 **Final Code → Test → Git → GitHub → Deploy → 서비스 확인** 입니다.

> 상태: **배포 전**. 배포를 마치면 6장의 표(주소·날짜·확인 결과)를 채웁니다.

## 1. 배포 구성

**Railway**(서버 + MySQL)에 배포합니다. 카드 등록 없이 GitHub 계정 인증으로 쓸 수 있는 체험판(30일, $5 크레딧)을 사용합니다.

```
[사용자 브라우저] --HTTPS--> [Railway 도메인 (*.up.railway.app)] --> [uvicorn 1개 프로세스 (FastAPI)] --사설망--> [Railway MySQL]
                                HTTPS 인증서는 Railway 가 자동 발급            Root Directory = backend          mysql.railway.internal
```

| 항목 | 값 | 이유 |
|---|---|---|
| 플랫폼 | Railway 체험판 | 카드 없이 서버와 DB 를 한 프로젝트에서 운영. HTTPS 자동 |
| Python | Railway 자동 감지 (`requirements.txt`) | 코드 변경 없이 빌드 |
| DB | Railway MySQL | MariaDB 와 같은 MySQL 계열이라 `models.py` 를 그대로 사용 (`mysql` 설정 포함). 테이블·데모 데이터는 서버 시작 시 자동 생성 |
| 앱 서버 | uvicorn **프로세스 1개** (`--workers 1`) | 로그인 잠금·인증 코드 기록이 서버 메모리에 있어 프로세스가 여러 개면 따로 셈 (`06_architecture.md` 4장) |
| 메일 | 사용 안 함 (`EMAIL_VERIFICATION=0`) | 체험판은 바깥으로 나가는 네트워크가 제한되어 SMTP 발송을 보장할 수 없음. 메일 서버를 쓸 수 있는 환경에서는 `MAIL_*` 설정 후 `1` 로 켬 |

**체험판 제한**

| 제한 | 대처 |
|---|---|
| 30일 또는 $5 크레딧 소진 시 무료 플랜($1/월)으로 바뀌고, 그 뒤 30일 안에 결제하지 않으면 DB 데이터 삭제 | 발표·평가 기간 운영용. 계속 운영하려면 8장 백업 후 유료 전환 또는 부록 A(VM) 방식 |
| 이메일 인증 미사용 | 발표에서 "운영 환경에서는 SMTP 연결 후 `EMAIL_VERIFICATION=1`" 로 설명. 인증 흐름 시연은 9장 LAN 실행(개발 모드)으로 |

## 2. 배포 전 확인 (Final Code → Test → Git)

- [x] `cd backend && python -m pytest` 전부 통과 (`09_test_result.md` 기록, 2026-10-19 347개 통과)
- [x] 공유 파일(`setup_mariadb.sql`, `.env.example`)에 실제 비밀번호 없음 (GitHub 기준 확인, 예시 값은 `여기에_비밀번호` 로 통일) · 커밋 전 `git status` 확인은 각자
- [x] 쓰지 않는 파일 정리 (`frontend/passwordreset_new.html`, 추적되던 `.pyc`, 쓰이지 않는 `FeedbackCreate` 삭제)
- [ ] `backend/requirements.txt` 에 `cryptography` 포함 (MySQL 8 이상 기본 로그인 방식 `caching_sha2_password` 를 PyMySQL 이 처리하는 데 필요. 없으면 시작 시 `cryptography package is required` 오류)
- [ ] 최종 커밋과 태그
  ```bash
  git commit -m "release: v1.0 프로젝트 최종 버전"
  git tag v1.0.0
  git push origin main --tags
  ```

## 3. Railway 준비 (처음 한 번)

1. [railway.com](https://railway.com) 에 **GitHub 계정으로** 가입 → 안내에 따라 GitHub 인증을 마칩니다 (인증해야 네트워크 제한이 없는 체험판).
2. **New Project → Deploy from GitHub repo** → `semiproject_01_D` 선택. 서비스 하나가 만들어지고 첫 배포가 시작됩니다 (설정 전이라 실패해도 괜찮음).
3. 같은 프로젝트 화면에서 **Create(+) → Database → MySQL** 을 추가합니다. 서비스 이름은 기본값 `MySQL` 그대로 둡니다 (4장 변수에서 이 이름을 씀).

## 4. 환경 변수 (서비스 → Variables)

`backend/.env` 파일 대신 Railway 화면에서 넣습니다. 값은 Railway 에만 저장되고 GitHub 에는 올라가지 않습니다.

| 이름 | 값 | 비고 |
|---|---|---|
| `DATABASE_URL` | `mysql+pymysql://${{MySQL.MYSQLUSER}}:${{MySQL.MYSQLPASSWORD}}@${{MySQL.MYSQLHOST}}:${{MySQL.MYSQLPORT}}/${{MySQL.MYSQLDATABASE}}?charset=utf8mb4` | `${{MySQL.…}}` 는 Railway 가 MySQL 서비스의 실제 값으로 바꿔 넣음. Railway 가 만들어 주는 `MYSQL_URL`(`mysql://…`)은 드라이버가 달라 **그대로 쓰면 안 됨** |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` 결과 | 예시 값이면 시작 로그에 경고 |
| `COOKIE_SECURE` | `1` | Railway 주소는 HTTPS |
| `EMAIL_VERIFICATION` | `0` | 1장 메일 항목 참고 |
| `TZ` | `Asia/Seoul` | 서버 기본 시간대가 UTC 라 한국 시간 오전 9시 전에는 '오늘'이 하루 전으로 계산됨 (오늘 날짜 CSV 리뷰가 '미래'로 거부, '최근 7일' 통계 어긋남). `TZ` 는 서버 시작 전에 정해져야 하므로 `.env` 가 아니라 여기에 넣음 |
| `LOGIN_IP_MAX_FAILS`, `EMAIL_SEND_LIMIT_PER_IP` | `100` (선택) | 발표장처럼 여러 사람이 같은 와이파이(같은 IP)로 접속할 때 |

## 5. 서비스 설정·실행 (Deploy)

서비스 → **Settings** 에서 아래 값을 넣으면 자동으로 다시 배포됩니다.

| 항목 | 값 | 이유 |
|---|---|---|
| Source → Root Directory | `backend` | `requirements.txt` 와 실제 서버 `main.py` 가 `backend/` 안에 있음 |
| Deploy → Custom Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips '*'` | Railway 가 정한 포트 사용. `--proxy-headers` 가 없으면 모든 사용자가 Railway 프록시 IP 로 보여 IP 기준 잠금이 서비스 전체를 막음 |
| Deploy → Healthcheck Path | `/api/v1/health` | 서버·DB 가 정상일 때만 배포 완료로 처리 |
| Networking → Public Networking | **Generate Domain** | `https://○○○.up.railway.app` 주소 생성 (6장에 기록) |

배포 로그(Deployments → View Logs)에서 확인할 것:
- `[PIN POINT] DB: mysql+pymysql://...` 접속 정보 (비밀번호는 `***`)
- `[PIN POINT][경고] ...` 문구가 없음 (`SECRET_KEY` 예시 값 등)
- 처음 배포면 데모 데이터가 들어감 → **바로 데모 계정 비밀번호 변경** (`README.md` 에 공개된 비밀번호이므로)

## 6. 서비스 확인 (최종 검증 기준)

일정표 10일차 최종 검증 기준과 확인 방법입니다. 배포 후 결과를 채웁니다.

| 기준 | 확인 방법 | 결과 |
|---|---|---|
| 프로그램 실행 가능 | Railway 서비스 상태 Active, `https://도메인/api/v1/health` → `{"status":"ok","database":"ok",...}` | |
| 핵심 기능 정상 | `07_test_plan.md` 시나리오 S-01\~S-12 를 배포 주소에서 실행 (이메일 인증 단계는 `EMAIL_VERIFICATION=0` 으로 생략) | |
| DB 연결 정상 | `/api/v1/health` 의 `"database": "ok"` (DB 가 꺼져 있으면 503), 배포 로그의 `[PIN POINT] DB: mysql+pymysql://...` | |
| Frontend·Backend 연결 정상 | 쇼핑몰 분석 화면 차트 표시 (`/api/v1/stats/*` 호출 성공) | |
| 오류 처리 가능 | 없는 주소 → 404 화면, 남의 상품 → 404, 로그인 5회 실패 → 잠금 안내 | |
| 시간대 | 오늘 날짜 리뷰가 든 CSV 업로드가 '작성일이 미래' 없이 추가됨 | |
| 모바일 | 휴대폰(LTE)으로 배포 주소 접속, 메뉴·차트 표시 | |
| README 존재 | 저장소 최상위 `README.md` | 있음 |
| Git History 존재 | `git log`, `v1.0.0` 태그 | |
| 발표 Demo 가능 | 시연용 계정으로 시나리오 진행 | |

| 항목 | 값 |
|---|---|
| 서비스 주소 | |
| 배포 날짜 | |
| 배포 버전 | v1.0.0 |
| 확인한 사람 | |

## 7. 업데이트·되돌리기

- **업데이트:** `main` 에 push 하면 Railway 가 자동으로 다시 빌드·배포합니다. 배포가 끝나기 전에는 이전 버전이 계속 응답합니다 (Healthcheck 통과 후 교체).
- **되돌리기:** 서비스 → Deployments 에서 이전 배포의 **⋮ → Redeploy**. 또는 `git revert` 후 push.
- 재배포·재시작하면 로그인 잠금·인증 코드 기록(서버 메모리)은 초기화됩니다. DB 데이터는 MySQL 서비스에 있으므로 유지됩니다.
- 분석 규칙(`MODEL_VERSION`)이 바뀐 버전이면 시작할 때 예전 분석 결과가 자동으로 다시 분석됩니다 (로그: `리뷰 N건을 다시 분석했습니다`).

## 8. 백업 (체험판 종료 전)

체험판이 끝난 뒤 결제하지 않으면 DB 가 삭제되므로, 남겨야 할 데이터가 있으면 미리 내려받습니다.

1. MySQL 서비스 → Settings → Networking → **TCP Proxy** 를 켜면 외부 접속 주소(`MYSQL_PUBLIC_URL`)가 생깁니다.
2. 내 PC 에서 (MySQL/MariaDB 클라이언트 필요):
   ```bash
   mysqldump -h 공개호스트 -P 공개포트 -u root -p railway > pinpoint_backup.sql
   ```
3. 백업이 끝나면 TCP Proxy 를 다시 끕니다 (DB 를 인터넷에 열어 두지 않음).

## 9. 예비: 노트북 LAN 실행 (발표장)

배포 주소나 발표장 네트워크에 문제가 생기면, 노트북에서 같은 와이파이의 기기들이 접속하게 합니다.

```powershell
ipconfig                                                   # IPv4 주소 확인 (예: 192.168.0.23)
python -m uvicorn main:app --host 0.0.0.0 --port 8000      # 레포 폴더에서 실행
```

- `backend/.env` 는 `COOKIE_SECURE=0` (http 접속), `MAIL_HOST` 를 비워 두면 인증 코드가 화면에 표시되는 개발 모드 → **이메일 인증 흐름까지 시연 가능**
- 처음 한 번 Windows 방화벽 허용 (관리자 PowerShell):
  `New-NetFirewallRule -DisplayName "Pinpoint 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Domain`
- 다른 기기에서 `http://192.168.0.23:8000` 으로 접속 (Wi-Fi 네트워크 프로필이 '개인'이어야 함)

---

## 부록 A. 리눅스 서버(VM) 직접 운영

체험판 이후에도 계속 운영하거나 메일 인증을 켜야 할 때의 방식입니다 (예: AWS Lightsail 서울 리전, Ubuntu, 1GB 이상).

```
[사용자 브라우저] --HTTPS--> [nginx (443)] --HTTP--> [uvicorn 1개 프로세스 :8000] --> [MariaDB :3306]
```

```bash
# 1) 시간대·패키지
sudo timedatectl set-timezone Asia/Seoul
sudo apt update && sudo apt install -y python3 python3-venv mariadb-server nginx git

# 2) 코드·가상환경
sudo mkdir -p /srv/pinpoint && sudo chown $USER /srv/pinpoint
git clone https://github.com/jjddee0222-axfullstack01/semiproject_01_D.git /srv/pinpoint
cd /srv/pinpoint && git checkout v1.0.0
python3 -m venv venv && venv/bin/pip install -r backend/requirements.txt

# 3) DB 계정 (setup_mariadb.sql 을 복사해 '여기에_비밀번호' 를 바꾼 뒤 실행, 원본은 고치지 않음)
cp backend/setup_mariadb.sql /tmp/setup.sql && nano /tmp/setup.sql
sudo mariadb < /tmp/setup.sql && rm /tmp/setup.sql

# 4) 환경 설정: DB_PASSWORD, SECRET_KEY, COOKIE_SECURE=1, MAIL_*(실제 SMTP), EMAIL_VERIFICATION=1
cp backend/.env.example backend/.env && chmod 600 backend/.env && nano backend/.env
```

**systemd** `/etc/systemd/system/pinpoint.service`

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

```bash
sudo chown -R www-data /srv/pinpoint
sudo systemctl daemon-reload && sudo systemctl enable --now pinpoint
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

- 업데이트: `git pull && venv/bin/pip install -r backend/requirements.txt && sudo systemctl restart pinpoint`
- 백업: `mariadb-dump -u root -p pinpoint > pinpoint_$(date +%Y%m%d).sql` (cron 으로 매일)
- 방화벽은 22·80·443 만 열고 3306(DB)은 열지 않습니다.
