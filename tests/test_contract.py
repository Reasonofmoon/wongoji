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


def _server_side_source():
    """서버 쪽 모듈을 한 덩어리로 읽는다. 파일이 갈라져도 계약은 그대로다."""
    import glob
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "server*.py"))):
        out.append(open(path, encoding="utf-8").read())
    return "\n".join(out)


def test_server_uses_assemble():
    """서버가 게이트를 다시 조립하지 않는다. chumsak_app이 유일한 조립기다."""
    src = _server_side_source()
    assert "CA.assemble" in src
    assert "CA.layout_indent" in src
    assert re.search(r"sents\[:-1\]", src) is None


def test_static_mount_stays_last():
    """'/'에 StaticFiles를 먼저 걸면 그 아래 API 경로가 가려진다."""
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    mount = src.index('app.mount("/"')
    for path in ("/api/chumsak", "/api/export", "/api/health"):
        assert src.index(path) < mount, "%s가 정적 마운트 뒤에 있다" % path


def test_static_assets_are_cache_busted():
    """HTML은 새것인데 JS는 캐시된 옛것인 상태를 막는다.

    이 상태가 되면 새 화면이 뜨는데 아무 동작도 안 한다. 원인을 코드에서 찾게 된다.
    """
    import hashlib
    import re
    html = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    for name, attr in (("app.css", "href"), ("app.js", "src")):
        blob = open(os.path.join(ROOT, "web", name), "rb").read()
        want = hashlib.sha1(blob).hexdigest()[:8]
        m = re.search(r'%s="%s\?v=([0-9a-f]+)"' % (attr, re.escape(name)), html)
        assert m, "%s 링크에 버전이 없다" % name
        assert m.group(1) == want, (
            "%s가 바뀌었는데 index.html의 버전이 옛것이다 (%s != %s). "
            "references/정적자산_캐시.md 참조" % (name, m.group(1), want))


def test_upload_dependency_is_declared():
    """UploadFile을 쓰면 python-multipart가 없을 때 **앱 전체가** import에서 죽는다.

    라우트 정의 시점에 RuntimeError가 나므로 OCR만 실패하는 것이 아니라 배포가 통째로
    내려간다. 로컬에만 깔려 있어 보이지 않았다.
    """
    server_py = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    if "UploadFile" not in server_py:
        return
    for name in ("requirements.txt", "pyproject.toml"):
        text = open(os.path.join(ROOT, name), encoding="utf-8").read()
        assert "python-multipart" in text, "%s에 python-multipart가 없다" % name
