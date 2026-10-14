"""
PIN POINT REVIEW - 로그인 세션 (화면과 /api/v1 이 함께 사용)

  - 로그인 시 무작위 토큰을 만들어 쿠키 session_id 로 발급하고, DB(sessions)에는 SHA-256 해시만 저장
  - 요청마다 쿠키 → 해시 → 세션 조회 → 만료·탈퇴 여부 확인 (06_architecture 4장)
  - 로그아웃·탈퇴 시 서버에서 세션 행을 삭제 → 기존 쿠키로는 접근 불가
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Request
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

try:
    from .db import get_session
    from .models import User, UserSession, UserStatus
    from .security import hash_session_token, new_session_token
except ImportError:
    from db import get_session
    from models import User, UserSession, UserStatus
    from security import hash_session_token, new_session_token

# 세션 쿠키 설정 (05_api_spec: session_id, HttpOnly, Secure, SameSite=Lax)
SESSION_COOKIE = "session_id"
SESSION_TTL = timedelta(days=7)
# 개발(http://127.0.0.1)에서는 Secure 쿠키가 전송되지 않을 수 있어 기본값 False, 운영(HTTPS)에서 1로 설정
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"


class LoginRequired(Exception):
    """로그인하지 않은 사용자가 보호된 화면/API에 접근 (화면: 로그인 페이지로, API: 401)"""


def get_current_user(request: Request, db: Session = Depends(get_session)) -> Optional[User]:
    user = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = db.scalar(
            select(User)
            .join(UserSession, UserSession.user_id == User.id)
            .where(UserSession.session_token_hash == hash_session_token(token),
                   UserSession.expires_at > datetime.now(),
                   User.status == UserStatus.ACTIVE)
        )
    request.state.user = user
    return user


def login_required(user: Optional[User] = Depends(get_current_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def start_session(db: Session, user: User, response: Response) -> None:
    """로그인: 세션 행 생성 + 쿠키 발급 (만료된 세션은 이때 정리)"""
    db.execute(delete(UserSession).where(UserSession.expires_at <= datetime.now()))
    token = new_session_token()
    db.add(UserSession(user_id=user.id, session_token_hash=hash_session_token(token),
                       expires_at=datetime.now() + SESSION_TTL))
    db.commit()
    response.set_cookie(SESSION_COOKIE, token, max_age=int(SESSION_TTL.total_seconds()),
                        httponly=True, secure=COOKIE_SECURE, samesite="lax")


def end_session(db: Session, request: Request, response: Response) -> None:
    """로그아웃: 현재 세션 행 삭제 + 쿠키 만료"""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(UserSession).where(UserSession.session_token_hash == hash_session_token(token)))
        db.commit()
    clear_cookie(response)


def end_all_sessions(db: Session, user: User) -> None:
    """해당 사용자의 모든 세션 삭제 (commit 은 호출한 쪽에서)"""
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))


def delete_account(db: Session, user: User) -> None:
    """회원 탈퇴 (US-04, D5) — 하드 삭제. users 행을 지우고 나머지는 DB 외래키 규칙에 맡긴다 (commit 은 호출한 쪽에서)

      CASCADE  : sessions, risk_keywords, shop_monthly_stats,
                 products → reviews → review_analysis · review_keywords · review_replies ·
                                       review_blind_logs · reply_suggestions, product_monthly_stats
      SET NULL : feedbacks.user_id (서비스 의견은 익명으로 남김), 답글 작성자·블라인드 처리자
      남는 것  : keywords (모든 셀러가 함께 쓰는 키워드 사전)

    ORM 관계를 거치지 않고 DELETE 한 번으로 처리해 연결된 행을 메모리에 불러오지 않는다.
    계정 행이 사라지므로 같은 이메일·사업자번호로 다시 가입할 수 있다 (UNIQUE 제약은 유지).
    """
    db.execute(delete(User).where(User.id == user.id).execution_options(synchronize_session=False))
    db.expunge(user)


def clear_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, secure=COOKIE_SECURE, samesite="lax")
