# -*- coding: utf-8 -*-
"""원고지 첨삭기 — 교사 검토 화면 서버.

    uvicorn server:app --port 8000

ANTHROPIC_API_KEY 등 키가 있으면 LLM 계층을 붙인다. CHUMSAK_NO_LLM=1이면 규칙만 돈다.

| 모듈 | 맡은 일 |
|------|---------|
| `server_config`   | 경로·상한·환경 |
| `server_store`    | 세션·인식 결과 디스크 저장 |
| `server_pipeline` | 원문 -> 첨삭 -> SVG |
| `server_ocr`      | 사진 입력 라우터 (`/api/ocr`) |

이 파일은 앱을 조립하고 나머지 라우트를 단다. **정적 마운트는 항상 맨 아래**에 온다 —
`/`에 StaticFiles를 먼저 걸면 그 아래 API 경로가 가려진다.
"""
import os
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import llm_host as LH
import wongoji_render as WR
from server_config import (DEMO_TEXT, MAX_TEXT, OUT, WEB_DIR, load_dotenv,
                           load_samples)
from server_store import (latest_session_id, load_ocr, load_session,  # noqa: F401
                          save_ocr, save_session, session_count)
from server_pipeline import (get_host, get_kiwi, make_spec,  # noqa: F401
                             run_pipeline)
import server_ocr

load_dotenv()

app = FastAPI(title="원고지 첨삭기")
app.include_router(server_ocr.router)


class ChumsakIn(BaseModel):
    text: str = ""
    grade: str = "초등 6학년"
    focus: list[str] | None = None
    llm_items: int = 8
    indirect: bool = False
    ocr_id: str | None = None


class ExportIn(BaseModel):
    text: str
    corrections: list[dict]
    review: dict = Field(default_factory=dict)
    format: str = "png"
    audience: str = "teacher"


class SettingsIn(BaseModel):
    provider: str = "xai"
    api_key: str = ""
    model: str = ""


@app.post("/api/chumsak")
def api_chumsak(body: ChumsakIn):
    text = (body.text or "").strip()
    if body.ocr_id:
        # 사진에서 온 원고는 교사가 확인한 본문만 쓴다. 클라이언트가 보낸 text는 버린다.
        rec = load_ocr(body.ocr_id)
        if rec is None:
            return JSONResponse({"error": "인식 결과를 찾을 수 없습니다."}, status_code=404)
        if not rec.get("confirmed"):
            return JSONResponse(
                {"error": "확인하지 않은 인식 결과입니다. 칸을 확인한 뒤 첨삭하세요."},
                status_code=409)
        text = (rec.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "본문이 비어 있습니다."}, status_code=400)
    if len(text) > MAX_TEXT:
        return JSONResponse({"error": "본문이 너무 깁니다(%d자). %d자까지."
                             % (len(text), MAX_TEXT)}, status_code=400)
    t0 = time.time()
    res = run_pipeline(text, grade=body.grade, focus=body.focus,
                       llm_items=body.llm_items, indirect=body.indirect)
    sid = uuid.uuid4().hex[:12]
    save_session(sid, res)
    return {"session": sid, "svg": res["svg"], "data": res["data"],
            "gate": res["gate"], "counts": res["counts"],
            "elapsed_s": round(time.time() - t0, 2)}


@app.get("/api/samples")
def api_samples():
    """오류가 든 시험용 원고 목록. 누구나 앱 성능을 직접 재 볼 수 있게 한다.

    `known`은 사람이 표시해 둔 오류 건수다. 앱이 표시한 부호와 자동으로 대조하지
    않는다 — 자동 채점은 정답 span이 필요하고, 그것은 `tests/corpus/`의 일이다.
    """
    return {"samples": load_samples()}


@app.get("/api/session")
def api_session(id: str | None = None):
    """화면 최초 로드용. 세션이 없으면 데모 원고로 하나 만든다."""
    sid = id or latest_session_id()
    res = load_session(sid) if sid else None
    if res is None:
        res = run_pipeline(DEMO_TEXT)
        sid = "demo"
        save_session(sid, res)
    return {"session": sid, "svg": res["svg"], "data": res["data"],
            "gate": res["gate"], "counts": res["counts"]}


@app.post("/api/export")
def api_export(body: ExportIn):
    """교사 검토 상태를 반영해 첨삭본을 낸다.

    승인·수정 -> 그대로 그린다.  기각 -> 되살림표로 남긴다.  미검토 -> 뺀다.
    학생용(PDF)은 미검토가 있으면 거절한다.
    """
    pending = sum(1 for c in body.corrections if c.get("state", "pending") == "pending")
    if body.audience == "student" and pending:
        return JSONResponse({"error": "미검토 항목이 %d건 있습니다. 모두 검토한 뒤 돌려주세요."
                             % pending}, status_code=400)
    draw, stet = [], 0
    for c in body.corrections:
        st = c.get("state", "pending")
        if st in ("approved", "edited"):
            draw.append(c)
        elif st == "rejected":
            d = dict(c)
            d["kind"] = "stet"
            d.pop("text", None)
            d["reason"] = "교사가 되살림 — " + (c.get("reason") or "")
            draw.append(d)
            stet += 1
    if not draw:
        return JSONResponse({"error": "승인된 항목이 없습니다."}, status_code=400)
    fmt = "pdf" if body.format == "pdf" or body.audience == "student" else "png"
    name = "chumsak_%s.%s" % (uuid.uuid4().hex[:8], fmt)
    spec = make_spec(body.text, draw, body.review, extra={
        "figure_title": "첨삭본",
        "out": os.path.join(OUT, name),
        "caption": "교사 검토 완료 · 승인 %d건, 되살림 %d건"
                   % (len(draw) - stet, stet),
    })
    info = WR.render(spec)
    return {"url": "/out/" + name, "file": info["out"], "approved": len(draw) - stet,
            "stet": stet, "unresolved": info["unresolved"]}


@app.get("/api/health")
def api_health():
    st = LH.status()
    st.update({"ok": True, "sessions": session_count(), "persist": True})
    return st


@app.get("/api/models")
def api_models():
    import llm_models as LM
    return LM.catalog_payload()


@app.post("/api/settings")
def api_settings(body: SettingsIn):
    provider = (body.provider or "gemini").lower().strip()
    if provider not in ("xai", "gemini", "anthropic", "openai"):
        return JSONResponse({"error": "provider는 xai, gemini, anthropic, openai 중 하나여야 합니다."},
                            status_code=400)
    payload = {"provider": provider}
    if body.api_key.strip():
        payload["api_key"] = body.api_key.strip()
    if body.model.strip():
        payload["model"] = body.model.strip()
    LH.save_settings(payload)
    try:
        host = get_host()
        if host is None:
            return JSONResponse({"error": "키를 읽었지만 호스트를 만들지 못했습니다."}, status_code=400)
        st = LH.status()
        st["ok"] = True
        return st
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/")
def index_page():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


app.mount("/out", StaticFiles(directory=OUT), name="out")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
