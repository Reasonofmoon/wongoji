# -*- coding: utf-8 -*-
"""모든 API 경로를 실제로 한 번씩 두드린다.

모듈을 가르면서 `server_config`에 `json` import가 빠졌는데 단위 테스트가 전부 통과했다.
파일을 직접 읽는 테스트만 있고 라우트를 부르는 테스트가 없었기 때문이다. 임포트 누락은
호출해 봐야 드러난다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["persist"] is True


def test_samples(client):
    r = client.get("/api/samples")
    assert r.status_code == 200
    assert len(r.json()["samples"]) >= 4


def test_models(client):
    assert client.get("/api/models").status_code == 200


def test_session(client):
    assert client.get("/api/session").status_code == 200


def test_index_and_static(client):
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_ocr_route_is_alive(client):
    """422는 '파일이 없다'는 정상 검증이다. python-multipart가 없으면 앱이 죽는다."""
    assert client.post("/api/ocr").status_code == 422


def test_chumsak_and_export(client):
    sm = client.get("/api/samples").json()["samples"][0]
    r = client.post("/api/chumsak", json={"text": sm["text"], "grade": sm["grade"]})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["corrections"]
    assert data["grid"]["nrows"] % 20 == 0        # 장 단위로 끊긴다

    corr = [dict(c, state="approved") for c in data["corrections"]]
    e = client.post("/api/export", json={
        "text": sm["text"], "corrections": corr,
        "review": {"good": "가", "fix": "나", "next": "다"},
        "format": "png", "audience": "teacher"})
    assert e.status_code == 200
    assert e.json()["url"].endswith(".png")


def test_every_module_imports():
    """가른 모듈이 각자 홀로 임포트되는지 본다. 옮기다 빠진 import를 잡는다."""
    import importlib
    for name in ("wongoji_style", "wongoji_text", "wongoji_grid", "wongoji_marks",
                 "wongoji_panel", "wongoji_render", "wongoji_svg", "ocr_wongoji",
                 "server_config", "server_store", "server_pipeline", "server_ocr",
                 "chumsak_app"):
        importlib.import_module(name)
