# -*- coding: utf-8 -*-
"""API 계약과 프론트 payload 키가 같은지 본다."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_payload_out_has_audience():
    js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    assert "audience: audience" in js
    assert 'exportSheet("png", "teacher")' in js
    assert 'exportSheet("pdf", "student")' in js


def test_compose_calls_chumsak():
    js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    html = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    assert "/api/chumsak" in js
    assert "/api/settings" in js
    assert "/api/models" in js or "j.catalog" in js
    assert 'id="src"' in html
    assert 'id="view-compose"' in html
    assert 'id="set-key"' in html


def test_no_score_in_ui():
    blob = ""
    for rel in ("web/index.html", "web/app.js", "server.py"):
        blob += open(os.path.join(ROOT, rel), encoding="utf-8").read()
    assert "점수" not in blob
    assert "등급" not in blob


def test_byok_catalog_has_current_flagships():
    import sys
    sys.path.insert(0, ROOT)
    import llm_models as LM
    payload = LM.catalog_payload()
    by = {p["id"]: [m["id"] for m in p["models"]] for p in payload["providers"]}
    assert "grok-4.6" in by["xai"]
    assert "claude-sonnet-5" in by["anthropic"]
    assert "gemini-3.7-flash" in by["gemini"]
    assert "gpt-5.6-sol" in by["openai"]
    assert LM.default_model("xai") == "grok-4.6"


def test_server_uses_assemble():
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    assert "CA.assemble" in src
    assert "CA.layout_indent" in src
    assert re.search(r"sents\[:-1\]", src) is None
