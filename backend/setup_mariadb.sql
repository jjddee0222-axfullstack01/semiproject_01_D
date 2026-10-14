-- PIN POINT REVIEW - MariaDB 최초 1회 설정 (root 계정으로 실행)
--
-- 실행 방법 (둘 중 하나)
--   1) 명령 프롬프트:  mariadb -u root -p < backend\setup_mariadb.sql
--   2) HeidiSQL 등에서 root 로 접속 → 이 파일 내용을 붙여 넣고 실행
--
-- 실행 전에 아래 '여기에_비밀번호' 를 원하는 비밀번호로 바꾸고, .env 의 DB_PASSWORD 에도 같은 값을 넣으세요.
-- ⚠️ 실제 비밀번호를 적은 상태로 이 파일을 커밋하지 마세요. 실행한 뒤에는 '여기에_비밀번호' 로 되돌려 두세요.
--    (실제 비밀번호는 git 에 올라가지 않는 backend/.env 에만 보관)
--
-- 이미 만든 계정의 비밀번호만 바꿀 때 (root 로 실행):
--   ALTER USER 'pinpoint'@'localhost' IDENTIFIED BY '새_비밀번호';
--   ALTER USER 'pinpoint'@'127.0.0.1' IDENTIFIED BY '새_비밀번호';
--   → backend/.env 의 DB_PASSWORD 도 같은 값으로 수정 후 서버 재시작
-- 테이블은 서버(uvicorn)를 처음 켤 때 자동으로 만들어집니다.

CREATE DATABASE IF NOT EXISTS pinpoint
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'pinpoint'@'localhost' IDENTIFIED BY '여기에 비밀번호';
CREATE USER IF NOT EXISTS 'pinpoint'@'127.0.0.1' IDENTIFIED BY '여기에 비밀번호';

GRANT ALL PRIVILEGES ON pinpoint.* TO 'pinpoint'@'localhost';
GRANT ALL PRIVILEGES ON pinpoint.* TO 'pinpoint'@'127.0.0.1';
FLUSH PRIVILEGES;
