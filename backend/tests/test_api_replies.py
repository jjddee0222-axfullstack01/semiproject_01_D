"""API 4장: CS 답글 (트리, 블라인드 리뷰 차단, 작성자 권한, 연쇄 삭제)"""
import pytest

from tests.conftest import API, error_code

pytestmark = pytest.mark.api


def _replies(review_id):
    return f"{API}/reviews/{review_id}/replies"


def test_reply_tree(api, ids):
    root = api.post(_replies(ids["risky_a"]), json={"content": "불편을 드려 죄송합니다."})
    assert root.status_code == 201
    child = api.post(_replies(ids["risky_a"]), json={"content": "교환 접수했습니다.", "parent_id": root.json()["id"]})
    assert child.status_code == 201

    tree = api.get(_replies(ids["risky_a"])).json()
    assert len(tree) == 1 and tree[0]["children"][0]["content"] == "교환 접수했습니다."
    detail = api.get(f"{API}/reviews/{ids['risky_a']}").json()
    assert detail["replies"][0]["children"][0]["id"] == child.json()["id"]


def test_reply_validation(api, ids):
    assert api.post(_replies(ids["risky_a"]), json={"content": ""}).status_code == 422
    r = api.post(_replies(ids["risky_a"]), json={"content": "x", "parent_id": 99999})
    assert r.status_code == 404 and error_code(r) == "PARENT_REPLY_NOT_FOUND"
    other_root = api.post(_replies(ids["positive_a"]), json={"content": "감사합니다"}).json()
    r = api.post(_replies(ids["risky_a"]), json={"content": "x", "parent_id": other_root["id"]})
    assert r.status_code == 404                                   # 다른 리뷰의 답글을 부모로 지정 불가


def test_no_reply_on_blinded_review(api, ids):
    api.post(f"{API}/reviews/{ids['risky_a']}/blind", json={"reason": "악성"})
    r = api.post(_replies(ids["risky_a"]), json={"content": "죄송합니다"})
    assert r.status_code == 409 and error_code(r) == "REVIEW_BLINDED"


def test_update_and_delete_reply(api, other_api, ids):
    root = api.post(_replies(ids["risky_a"]), json={"content": "처음"}).json()
    api.post(_replies(ids["risky_a"]), json={"content": "하위", "parent_id": root["id"]})

    r = api.patch(f"{API}/replies/{root['id']}", json={"content": "수정됨"})
    assert r.status_code == 200 and r.json()["content"] == "수정됨"
    assert other_api.patch(f"{API}/replies/{root['id']}", json={"content": "x"}).status_code == 403
    assert other_api.delete(f"{API}/replies/{root['id']}").status_code == 403

    assert api.delete(f"{API}/replies/{root['id']}").status_code == 204
    assert api.get(_replies(ids["risky_a"])).json() == []          # 하위 답글까지 삭제
    assert error_code(api.patch(f"{API}/replies/{root['id']}", json={"content": "x"})) == "REPLY_NOT_FOUND"
