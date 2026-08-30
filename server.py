# -*- coding: utf-8 -*-
"""원고지 첨삭기 — 교사 검토 화면 서버(1단계 프로토타입).

실행:  uvicorn server:app --port 8000
       LLM 계층을 쓰려면 host.llm이 있는 환경에서 실행한다.
       host가 없으면 규칙 계층만 돌고 총평은 비어 있다(CHUMSAK_NO_LLM=1로 강제 가능).
"""
import json
import os
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import chumsak_app as CA
import wongoji_render as WR
import wongoji_svg as WS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

app = FastAPI(title="원고지 첨삭기")
SESSIONS = {}

DEMO_TEXT = ("어제 나는 친구와같이 놀이 터에서 놀았다. 그런데 갑자기 비 왔다 "
             "그래서 우리는 집으로 뛰어갔다. 아주 정말 재미있었다.")


# ---------------------------------------------------------------- 의존성
def get_kiwi():
    if not hasattr(get_kiwi, "_k"):
        from kiwipiepy import Kiwi
        get_kiwi._k = Kiwi()
    return get_kiwi._k


HOST = None          # 커널에서 실행할 때 server.HOST = host 로 주입한다


def get_host():
    if os.environ.get("CHUMSAK_NO_LLM"):
        return None
    if HOST is not None:
        return HOST
    try:
        import builtins
        return getattr(builtins, "host", None) or __import__("host")
    except Exception:
        return None


# ---------------------------------------------------------------- 파이프라인
def run_pipeline(text, grade="초등 6학년", focus=None, llm_items=6):
    """규칙 계층 + (가능하면) LLM 계층 -> 게이트 -> SVG."""
    kiwi = get_kiwi()
    rules = CA.rule_layer(text, kiwi)
    host = get_host()
    llm, review, refused = [], {}, []
    if host is not None:
        try:
            llm, review, refused = CA.llm_layer(text, host, grade=grade,
                                                max_items=llm_items)
        except Exception as exc:                      # LLM 실패는 치명적이지 않다
            refused = [{"kind": "-", "target": "", "reason": "",
                        "drop_reason": "LLM 계층 실패: %s" % exc}]
    llm, bogus = CA.normalize(text, llm)
    merged, dropped = CA.verify(text, CA.dedupe(rules + llm))
    merged, clashed = CA.drop_overlaps(merged)
    dropped += refused + bogus + clashed
    drawn, held = CA.focus_filter(merged, focus=focus, max_items=12)

    spec = {"text": text, "indent": 0 if any(c["kind"] == "indent" for c in drawn) else 1,
            "ncols": 20, "nrows": 2 * (len(text) // 18 + 3) + 2, "double_space": True,
            "corrections": drawn, "review": review}
    built = WS.build(spec)
    return {"svg": built["svg"], "data": built["data"],
            "gate": [{k: v for k, v in c.items() if k != "_span"} for c in dropped],
            "counts": {"rule": len(rules), "llm": len(llm), "drawn": len(drawn),
                       "held": len(held), "dropped": len(dropped)},
            "spec": spec}


# ---------------------------------------------------------------- 모델
class ChumsakIn(BaseModel):
    text: str
    grade: str = "초등 6학년"
    focus: list[str] | None = None
    llm_items: int = 6


class ExportIn(BaseModel):
    text: str
    corrections: list[dict]
    review: dict = {}
    format: str = "png"


# ---------------------------------------------------------------- 엔드포인트
@app.post("/api/chumsak")
def api_chumsak(body: ChumsakIn):
    t0 = time.time()
    res = run_pipeline(body.text, grade=body.grade, focus=body.focus,
                       llm_items=body.llm_items)
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = res
    return {"session": sid, "svg": res["svg"], "data": res["data"],
            "gate": res["gate"], "counts": res["counts"],
            "elapsed_s": round(time.time() - t0, 2)}


@app.get("/api/session")
def api_session():
    """화면 최초 로드용. 세션이 없으면 데모 원고로 하나 만든다."""
    if not SESSIONS:
        res = run_pipeline(DEMO_TEXT)
        SESSIONS["demo"] = res
    sid = list(SESSIONS)[-1]
    res = SESSIONS[sid]
    return {"session": sid, "svg": res["svg"], "data": res["data"],
            "gate": res["gate"], "counts": res["counts"]}


@app.post("/api/export")
def api_export(body: ExportIn):
    """교사 검토 상태를 반영해 첨삭본을 낸다.

    승인·수정 -> 그대로 그린다.  기각 -> 되살림표로 남긴다.  미검토 -> 뺀다.
    """
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
    fmt = "pdf" if body.format == "pdf" else "png"
    name = "chumsak_%s.%s" % (uuid.uuid4().hex[:8], fmt)
    spec = {"text": body.text,
            "indent": 0 if any(c["kind"] == "indent" for c in draw) else 1,
            "ncols": 20, "nrows": 2 * (len(body.text) // 18 + 3) + 2,
            "double_space": True, "corrections": draw, "review": body.review,
            "figure_title": "첨삭본", "out": os.path.join(OUT, name),
            "caption": "교사 검토 완료 · 승인 %d건, 되살림 %d건"
                       % (len(draw) - stet, stet)}
    info = WR.render(spec)
    return {"url": "/out/" + name, "file": info["out"], "approved": len(draw) - stet,
            "stet": stet, "unresolved": info["unresolved"]}


@app.get("/api/health")
def api_health():
    return {"ok": True, "llm": get_host() is not None,
            "sessions": len(SESSIONS)}


app.mount("/out", StaticFiles(directory=OUT), name="out")
app.mount("/", StaticFiles(directory=os.path.join(HERE, "web"), html=True), name="web")
