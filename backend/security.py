"""
PIN POINT REVIEW - 비밀번호 해시 / 세션 토큰

비밀번호 : PBKDF2-SHA256 (파이썬 표준 라이브러리, 단방향 해시)
           ※ 문서의 'argon2 등' 중 하나. argon2 로 바꾸려면 hash_password/verify_password 만 교체
세션 토큰: 쿠키에는 원본, DB(sessions.session_token_hash)에는 SHA-256 해시만 저장
"""
import hashlib
import hmac
import secrets

_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(check.hex(), digest)


def new_session_token() -> str:
    """쿠키 session_id 에 넣을 무작위 토큰"""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
