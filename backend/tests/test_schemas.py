"""Pydantic 스키마 입력 검증 (DB·서버 불필요)"""
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

import schemas as S
from models import IssueType, MallPlatform

pytestmark = pytest.mark.unit

SIGNUP = {"email": " Seller@Pinpoint.KR ", "password": "Abcd123!", "name": "김셀러", "mall_name": "몰",
          "mall_platform": "NAVER", "business_number": "123-45-67890"}


def test_signup_normalizes_email_and_business_number():
    s = S.SignupRequest.model_validate(SIGNUP)
    assert s.email == "seller@pinpoint.kr"
    assert s.business_number == "1234567890"
    assert s.mall_platform is MallPlatform.NAVER


@pytest.mark.parametrize("field, value, message", [
    ("email", "not-an-email", "이메일 형식"),
    ("password", "abcd1234", "대/소문자"),
    ("password", "Ab1!", "8~64자"),
    ("business_number", "12-34", "숫자 10자리"),
    ("mall_platform", "SMARTSTORE", "NAVER"),
    ("name", "", "at least 1"),
])
def test_signup_rejects_invalid(field, value, message):
    with pytest.raises(ValidationError, match=message):
        S.SignupRequest.model_validate(SIGNUP | {field: value})


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        S.SignupRequest.model_validate(SIGNUP | {"role": "admin"})


def test_user_update_needs_at_least_one_field():
    with pytest.raises(ValidationError, match="하나 이상"):
        S.UserUpdate.model_validate({})
    assert S.UserUpdate.model_validate({"business_number": "111-22-33333"}).business_number == "1112233333"


def test_password_change_must_differ():
    with pytest.raises(ValidationError, match="같습니다"):
        S.PasswordChangeRequest.model_validate({"current_password": "Abcd123!", "new_password": "Abcd123!"})


@pytest.mark.parametrize("payload", [{}, {"reason": "   "}])
def test_blind_reason_required(payload):
    with pytest.raises(ValidationError):
        S.BlindRequest.model_validate(payload)


@pytest.mark.parametrize("model", [S.StatsQuery, S.ReviewListQuery, S.CompareQuery])
def test_date_range_order_checked_everywhere(model):
    data = {"from": "2026-10-10", "to": "2026-10-01"}
    if model is S.CompareQuery:
        data["product_ids"] = "1,2"
    with pytest.raises(ValidationError, match="늦을 수 없습니다"):
        model.model_validate(data)


@pytest.mark.parametrize("value, expected", [("1,2", [1, 2]), (["1", "2"], [1, 2]), (["1,2"], [1, 2])])
def test_compare_product_ids_formats(value, expected):
    assert S.CompareQuery.model_validate({"product_ids": value}).product_ids == expected


@pytest.mark.parametrize("value", ["1", "1,1", "1,2,3"])
def test_compare_needs_two_distinct_products(value):
    with pytest.raises(ValidationError, match="서로 다른"):
        S.CompareQuery.model_validate({"product_ids": value})


def test_pagination_bounds_and_offset():
    q = S.RiskReviewQuery.model_validate({"page": 3, "size": 10, "issue_type": "DELIVERY"})
    assert q.offset == 20 and q.issue_type is IssueType.DELIVERY and q.sort == "severity"
    with pytest.raises(ValidationError):
        S.PageParams.model_validate({"size": 101})
    with pytest.raises(ValidationError):
        S.PageParams.model_validate({"page": 0})


def test_risk_keyword_rules():
    with pytest.raises(ValidationError):
        S.RiskKeywordCreate.model_validate({"word": "환불", "weight": 0})
    with pytest.raises(ValidationError, match="수정할 항목"):
        S.RiskKeywordUpdate.model_validate({})


def test_review_create_rejects_future_date():
    with pytest.raises(ValidationError, match="미래"):
        S.ReviewCreate.model_validate({"product_id": 1, "content": "x", "rating": 3,
                                       "reviewed_at": str(date.today() + timedelta(days=1))})


def test_all_schemas_produce_json_schema():
    """FastAPI /docs 생성에 필요한 JSON Schema 가 모두 만들어지는지"""
    import inspect
    from pydantic import BaseModel
    classes = [c for _, c in inspect.getmembers(S, inspect.isclass)
               if issubclass(c, BaseModel) and c.__module__ == S.__name__ and c is not S.Page]
    assert len(classes) > 40
    for c in classes:
        c.model_json_schema()
    S.Page[S.ReviewOut].model_json_schema()
