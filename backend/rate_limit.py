"""
PIN POINT REVIEW - 시도 횟수 제한 (로그인 · 비밀번호 찾기 · 인증 코드 발송)

왜 서버에 저장하나
  예전에는 실패 횟수를 브라우저 쿠키(세션)에 저장해서, 쿠키를 지우거나 예전 쿠키로 되돌리면
  잠금이 풀렸다. 이제는 서버 메모리에 '이메일'과 'IP' 기준으로 기록하므로 브라우저에서 우회할 수 없다.

한계 (문서 docs/06_architecture.md 참고)
  - 서버 프로세스 메모리에 저장 → 서버를 재시작하면 기록이 초기화됨
  - uvicorn 을 여러 프로세스(--workers 2 이상)로 띄우면 프로세스마다 따로 셈 → 이 프로젝트는 1개 프로세스로 실행
  - DB 구조를 바꾸지 않기 위해 이 방식을 사용. 서비스 규모가 커지면 Redis 등으로 옮긴다
"""
import threading
import time
from typing import Optional


class AttemptLimiter:
    """window_seconds 안에 max_fails 번 실패하면 lock_seconds 동안 잠금"""

    def __init__(self, max_fails: int, lock_seconds: int, window_seconds: Optional[int] = None):
        self.max_fails = max_fails
        self.lock_seconds = lock_seconds
        self.window_seconds = window_seconds or lock_seconds
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _entry(self, key: str, now: float) -> dict:
        entry = self._data.get(key)
        if entry is None or (entry["until"] <= now and now - entry["first"] > self.window_seconds):
            entry = {"count": 0, "first": now, "until": 0.0}
            self._data[key] = entry
        return entry

    def _prune(self, now: float) -> None:
        """오래된 기록 정리 (메모리가 계속 늘지 않게)"""
        if len(self._data) < 1000:
            return
        for key in [k for k, e in self._data.items()
                    if e["until"] <= now and now - e["first"] > self.window_seconds]:
            del self._data[key]

    def locked_for(self, *keys: str) -> int:
        """잠겨 있으면 남은 초, 아니면 0 (여러 키 중 가장 긴 값)"""
        now = time.time()
        with self._lock:
            remain = [e["until"] - now for k in keys if (e := self._data.get(k)) and e["until"] > now]
        return int(max(remain)) + 1 if remain else 0

    def fail(self, *keys: str) -> int:
        """실패 1회 기록 → 첫 번째 키의 누적 실패 횟수 (이번에 잠겼으면 max_fails)"""
        now = time.time()
        counts = []
        with self._lock:
            self._prune(now)
            for key in keys:
                entry = self._entry(key, now)
                entry["count"] += 1
                if entry["count"] >= self.max_fails:
                    entry.update(count=0, first=now, until=now + self.lock_seconds)
                    counts.append(self.max_fails)
                else:
                    counts.append(entry["count"])
        return counts[0] if counts else 0

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._data.pop(key, None)

    def clear(self) -> None:
        """(테스트용) 모든 기록 삭제"""
        with self._lock:
            self._data.clear()


class RateCounter:
    """window_seconds 안에 limit 번까지만 허용 (인증 메일 발송 횟수 제한)"""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, *keys: str) -> bool:
        """모든 키가 한도 안이면 기록하고 True, 하나라도 넘었으면 기록하지 않고 False"""
        now = time.time()
        with self._lock:
            recent = {k: [t for t in self._hits.get(k, []) if now - t < self.window_seconds] for k in keys}
            if any(len(v) >= self.limit for v in recent.values()):
                self._hits.update(recent)
                return False
            for k, v in recent.items():
                v.append(now)
                self._hits[k] = v
            if len(self._hits) > 5000:          # 정리
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window_seconds}
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


# ── 서비스 전체에서 쓰는 제한 값
LOGIN_MAX_FAILS = 5                  # 같은 이메일로 5번 틀리면
LOGIN_LOCK_SECONDS = 10 * 60         #   10분 잠금
LOGIN_IP_MAX_FAILS = 20              # 같은 IP 에서 (여러 이메일로) 20번 틀려도 10분 잠금
RESET_MAX_FAILS = 5                  # 비밀번호 찾기: 정보 불일치 5번 → 10분 잠금
RESET_LOCK_SECONDS = 10 * 60

login_by_email = AttemptLimiter(LOGIN_MAX_FAILS, LOGIN_LOCK_SECONDS)
login_by_ip = AttemptLimiter(LOGIN_IP_MAX_FAILS, LOGIN_LOCK_SECONDS)
password_reset = AttemptLimiter(RESET_MAX_FAILS, RESET_LOCK_SECONDS)


def client_ip(request) -> str:
    """요청한 PC 의 IP (프록시 뒤에 배포하면 프록시 IP 가 나오므로 docs/10_deployment.md 참고)"""
    return request.client.host if request.client else "unknown"


def clear_all() -> None:
    """(테스트용) 모든 제한 기록 초기화"""
    for limiter in (login_by_email, login_by_ip, password_reset):
        limiter.clear()


# ── 로그인 (화면 /login 과 API /api/v1/auth/login 공통)
def login_locked_seconds(email: str, ip: str) -> int:
    return max(login_by_email.locked_for(email), login_by_ip.locked_for(ip))


def login_failed(email: str, ip: str) -> int:
    """실패 기록 → 이 이메일의 남은 시도 횟수 (0 이면 지금 잠김)"""
    login_by_ip.fail(ip)
    count = login_by_email.fail(email)
    return max(LOGIN_MAX_FAILS - count, 0)


def login_succeeded(email: str) -> None:
    login_by_email.reset(email)


def lock_message(seconds: int, what: str = "로그인") -> str:
    minutes = max(1, (seconds + 59) // 60)
    return f"{what} 시도가 너무 많아 잠시 잠겼습니다. {minutes}분 뒤에 다시 시도해 주세요."


# ── 서명 키 점검 (서버 시작 시)
WEAK_SECRET_KEYS = {"", "dev-secret-change-me", "change-this-to-a-long-random-string", "test-secret-key"}


def secret_key_warning(secret: str) -> str:
    """SECRET_KEY 가 비었거나 예시 값 그대로면 경고 문구, 괜찮으면 빈 문자열"""
    if secret in WEAK_SECRET_KEYS or len(secret) < 16:
        return ("[PIN POINT][경고] SECRET_KEY 가 설정되지 않았거나 예시 값 그대로입니다. "
                "backend/.env 에 길고 무작위인 값을 넣으세요. "
                "(만드는 법: python -c \"import secrets; print(secrets.token_urlsafe(32))\")")
    return ""
