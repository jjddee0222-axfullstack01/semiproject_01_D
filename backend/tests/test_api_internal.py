"""API 8장: 내부 데이터 파이프라인 (X-Internal-Key, CSV 적재, 분석)"""
import csv

import pytest
from sqlalchemy import delete, select

import models as m
from tests.conftest import API, INTERNAL_HEADERS, error_code

pytestmark = pytest.mark.api
INGEST = f"{API}/internal/ingest"


@pytest.fixture
def dataset(tmp_path):
    """적재용 CSV: 정상 2, 같은 파일 내 중복 1, 결측·형식 오류 3"""
    path = tmp_path / "reviews.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["product_name", "category", "reviewer_name", "rating", "content", "reviewed_at"])
        w.writerow(["신상품 D", "리빙", "김가나", "5", "<b>배송</b> 빨라요!!!! 👍", "2026-10-01"])
        w.writerow(["신상품 D", "리빙", "김가나", "5", "<b>배송</b> 빨라요!!!! 👍", "2026-10-01"])
        w.writerow(["신상품 D", "리빙", "박다라", "1", "벌레가 나왔어요 환불해주세요", "2026.10.02"])
        w.writerow(["신상품 D", "리빙", "", "", "평점 없음", "2026-10-03"])
        w.writerow(["", "", "x", "3", "상품명 없음", "2026-10-03"])
        w.writerow(["신상품 D", "리빙", "최", "4", "날짜 오류", "어제"])
    return str(path)


def _body(dataset, batch="b1"):
    return {"batch_name": batch, "source_path": dataset, "seller_id": 1}


@pytest.mark.parametrize("headers, code", [({}, "INVALID_INTERNAL_KEY"),
                                           ({"X-Internal-Key": "wrong"}, "INVALID_INTERNAL_KEY")])
def test_internal_key_required(client, dataset, headers, code):
    r = client.post(INGEST, json=_body(dataset), headers=headers)
    assert r.status_code == 403 and error_code(r) == code


def test_internal_disabled_without_key(client, dataset, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    assert error_code(client.post(INGEST, json=_body(dataset), headers=INTERNAL_HEADERS)) == "INTERNAL_API_DISABLED"


def test_ingest_counts_and_cleaning(api, dataset):
    log = api.post(INGEST, json=_body(dataset), headers=INTERNAL_HEADERS)
    assert log.status_code == 201
    assert (log.json()["total_count"], log.json()["duplicate_count"], log.json()["missing_count"]) == (6, 1, 3)

    product = [p for p in api.get(f"{API}/products").json()["items"] if p["name"] == "신상품 D"][0]
    reviews = api.get(f"{API}/products/{product['id']}/reviews").json()["items"]
    assert len(reviews) == 2 and all(r["analysis"] for r in reviews)
    detail = api.get(f"{API}/reviews/{[r for r in reviews if r['rating'] == 5][0]['id']}").json()
    assert detail["content_raw"].startswith("<b>배송</b>") and detail["content_clean"] == "배송 빨라요!!"

    again = api.post(INGEST, json=_body(dataset, "b2"), headers=INTERNAL_HEADERS).json()
    assert again["duplicate_count"] == 3                                   # 이미 DB 에 있는 리뷰
    logs = api.get(f"{API}/internal/ingest-logs", headers=INTERNAL_HEADERS).json()
    assert [x["batch_name"] for x in logs] == ["b2", "b1"]


@pytest.mark.parametrize("change, message", [
    ({"source_path": "/no/such/file.csv"}, "파일을 찾을 수 없습니다"),
])
def test_ingest_errors(client, dataset, change, message):
    r = client.post(INGEST, json=_body(dataset) | change, headers=INTERNAL_HEADERS)
    assert r.status_code == 422 and error_code(r) == "INGEST_FAILED" and message in r.json()["message"]


def test_ingest_missing_columns(client, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("name,stars\nA,5\n", encoding="utf-8")
    r = client.post(INGEST, json={"batch_name": "x", "source_path": str(path), "seller_id": 1}, headers=INTERNAL_HEADERS)
    assert r.status_code == 422 and "필수 컬럼" in r.json()["message"]


def test_ingest_unknown_seller(client, dataset):
    r = client.post(INGEST, json=_body(dataset) | {"seller_id": 999}, headers=INTERNAL_HEADERS)
    assert error_code(r) == "SELLER_NOT_FOUND"


def test_analyze_pending_and_reanalyze(client, session):
    session.execute(delete(m.ReviewAnalysis)); session.commit()
    r = client.post(f"{API}/internal/analyze", json={"limit": 5}, headers=INTERNAL_HEADERS)
    assert r.json() == {"analyzed_count": 5, "model_version": "rule-v2"}
    assert client.post(f"{API}/internal/analyze", json={"limit": 100}, headers=INTERNAL_HEADERS).json()["analyzed_count"] == 6
    assert client.post(f"{API}/internal/analyze", json={"limit": 100}, headers=INTERNAL_HEADERS).json()["analyzed_count"] == 0
    r = client.post(f"{API}/internal/analyze", json={"limit": 100, "reanalyze_model_version": "rule-v2"},
                    headers=INTERNAL_HEADERS)
    assert r.json()["analyzed_count"] == 11


def test_internal_api_hidden_from_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("/internal/" in p for p in paths)
    assert f"{API}/stats/summary" in paths and f"{API}/auth/login" in paths
