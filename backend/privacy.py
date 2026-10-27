"""
PIN POINT REVIEW - 리뷰 속 개인정보 가리기 (v1.2)

리뷰 원문(content_raw)은 그대로 보존하고, 화면·API 응답·CSV·알림 메일에 보여 줄 때만 가립니다.
  - 휴대폰·전화번호: 010-1234-5678, 01012345678, 02-123-4567, 010 1234 5678 → 010-****-****
  - 이메일: abc@naver.com → a**@naver.com
※ 블라인드 신고 자료(exports/blinded-reviews.csv)는 플랫폼 신고 근거라 원문 그대로 내보냄
"""
import re

_PHONE = re.compile(r"(?<!\d)(01[016789]|0[2-6][0-9]?|070)[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)")
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def mask_pii(text):
    """문자열 속 전화번호·이메일을 가림 (None·빈 문자열은 그대로)"""
    if not text:
        return text
    text = _PHONE.sub(lambda m: f"{m.group(1)}-****-****", text)
    return _EMAIL.sub(lambda m: f"{m.group(1)}**@{m.group(2)}", text)


def has_pii(text) -> bool:
    return bool(text) and bool(_PHONE.search(text) or _EMAIL.search(text))
