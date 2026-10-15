"""
PIN POINT REVIEW - 이메일 인증 코드 (회원가입 · 비밀번호 변경)

흐름
  1) 화면에서 '인증 코드 받기' → POST /email-code {purpose, email}
  2) 6자리 코드를 메일로 발송 (10분 유효, 재발송은 60초 뒤부터, 5번 틀리면 코드 폐기)
  3) 폼을 제출할 때 코드를 함께 보내면 check_code() 로 확인

저장 위치
  코드 자체는 저장하지 않고 HMAC 해시만 서명된 세션 쿠키(pp_flash)에 보관 → DB 구조 변경 없음

메일 발송 설정 (backend/.env)
  MAIL_HOST, MAIL_PORT(기본 587), MAIL_USER, MAIL_PASSWORD, MAIL_FROM, MAIL_USE_TLS(기본 1)
  MAIL_HOST 가 비어 있으면 '개발 모드': 메일 대신 서버 콘솔에 코드를 출력하고 화면에도 보여 줌
  EMAIL_VERIFICATION=0 이면 인증 코드 확인을 끔 (기존 테스트·로컬 시연용)
"""
import hashlib
import hmac
import os
import secrets
import smtplib
import time
from email.message import EmailMessage
from typing import Optional

CODE_VALID_SECONDS = 10 * 60
RESEND_COOLDOWN_SECONDS = 60
CODE_MAX_TRIES = 5
SESSION_KEY = "email_codes"
PURPOSES = {"signup": "회원가입", "reset": "비밀번호 변경"}


def verification_enabled() -> bool:
    return os.environ.get("EMAIL_VERIFICATION", "1") != "0"


def dev_mode() -> bool:
    """메일 서버 설정이 없으면 개발 모드 (코드를 화면·콘솔에 표시)"""
    return not os.environ.get("MAIL_HOST")


def _digest(purpose: str, email: str, code: str) -> str:
    secret = os.environ.get("SECRET_KEY", "dev-secret-change-me").encode()
    return hmac.new(secret, f"{purpose}:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def send_mail(to: str, subject: str, body: str) -> None:
    """SMTP 로 메일 발송 (실패하면 예외)"""
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USER", "")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host, port = os.environ["MAIL_HOST"], int(os.environ.get("MAIL_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if os.environ.get("MAIL_USE_TLS", "1") != "0":
            smtp.starttls()
        if os.environ.get("MAIL_USER"):
            smtp.login(os.environ["MAIL_USER"], os.environ.get("MAIL_PASSWORD", ""))
        smtp.send_message(msg)


def issue_code(session: dict, purpose: str, email: str, *, deliver: bool = True) -> tuple[bool, str, Optional[str]]:
    """인증 코드 발급 → (성공 여부, 안내 문구, 개발 모드일 때만 코드)

    deliver=False 면 코드를 만들지만 메일은 보내지 않음 (가입되지 않은 이메일로 비밀번호 변경을 요청한 경우:
    같은 안내 문구를 보여 줘서 가입 여부를 알 수 없게 함)
    """
    codes = session.setdefault(SESSION_KEY, {})
    now = time.time()
    previous = codes.get(purpose)
    if previous and previous["email"] == email and now - previous["sent"] < RESEND_COOLDOWN_SECONDS:
        wait = int(RESEND_COOLDOWN_SECONDS - (now - previous["sent"])) + 1
        return False, f"{wait}초 뒤에 다시 요청할 수 있습니다.", None

    code = f"{secrets.randbelow(1_000_000):06d}"
    codes[purpose] = {"email": email, "hash": _digest(purpose, email, code), "sent": now,
                      "exp": now + CODE_VALID_SECONDS, "tries": 0}
    session[SESSION_KEY] = codes            # 세션 쿠키 갱신

    message = f"{email} 로 인증 코드를 보냈습니다. 10분 안에 입력해 주세요."
    if not deliver:
        return True, message, None
    if dev_mode():
        print(f"[PIN POINT][개발 모드] {PURPOSES[purpose]} 인증 코드 → {email}: {code}")
        return True, message, code
    try:
        send_mail(email, f"[PIN POINT REVIEW] {PURPOSES[purpose]} 인증 코드",
                  f"인증 코드: {code}\n\n10분 안에 입력해 주세요. 요청하지 않았다면 이 메일을 무시하세요.")
    except Exception as exc:                # 메일 서버 오류 → 코드 폐기
        print(f"[PIN POINT] 인증 메일 발송 실패: {exc!r}")
        codes.pop(purpose, None)
        session[SESSION_KEY] = codes
        return False, "인증 메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.", None
    return True, message, None


def check_code(session: dict, purpose: str, email: str, code: str) -> Optional[str]:
    """맞으면 None (코드는 1회용이라 바로 폐기), 틀리면 사용자에게 보여 줄 오류 문구"""
    if not verification_enabled():
        return None
    codes = session.get(SESSION_KEY) or {}
    entry = codes.get(purpose)
    code = (code or "").strip()
    if not entry or entry["email"] != email:
        return "이메일 인증 코드를 먼저 받아 주세요."
    if entry["exp"] < time.time():
        codes.pop(purpose, None)
        session[SESSION_KEY] = codes
        return "인증 코드가 만료되었습니다. 다시 받아 주세요."
    if not code:
        return "이메일로 받은 인증 코드를 입력해 주세요."
    if not hmac.compare_digest(entry["hash"], _digest(purpose, email, code)):
        entry["tries"] += 1
        if entry["tries"] >= CODE_MAX_TRIES:
            codes.pop(purpose, None)
            session[SESSION_KEY] = codes
            return f"인증 코드를 {CODE_MAX_TRIES}번 틀렸습니다. 코드를 다시 받아 주세요."
        session[SESSION_KEY] = codes
        return f"인증 코드가 올바르지 않습니다. ({entry['tries']}/{CODE_MAX_TRIES})"
    codes.pop(purpose, None)
    session[SESSION_KEY] = codes
    return None
