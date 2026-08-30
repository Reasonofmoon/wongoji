# -*- coding: utf-8 -*-
"""원고지 첨삭기 — 교사 검토 화면 서버.

실행:  uvicorn server:app --port 8000
       ANTHROPIC_API_KEY가 있으면 LLM 계층을 붙인다.
       CHUMSAK_NO_LLM=1 이면 규칙 계층만 돈다.
"""
import json
import os
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import chumsak_app as CA
import llm_host as LH
import wongoji_render as WR
import wongoji_svg as WS

HERE = os.path.dirname(os.path.abspath(__file__))
ON_VERCEL = bool(os.environ.get("VERCEL"))
DATA_ROOT = "/tmp/wongoji" if ON_VERCEL else HERE
if ON_VERCEL:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    os.environ.setdefault("HOME", "/tmp")
OUT = os.path.join(DATA_ROOT, "out")
SESS_DIR = os.path.join(DATA_ROOT, "data", "sessions")
os.makedirs(OUT, exist_ok=True)
os.makedirs(SESS_DIR, exist_ok=True)


def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_dotenv()

app = FastAPI(title="원고지 첨삭기")
MAX_TEXT = 4000
INDEX_PATH = os.path.join(SESS_DIR, "_index.json")

DEMO_TEXT = ("어제 나는 친구와같이 놀이 터에서 놀았다. 그런데 갑자기 비 왔다 "
             "그래서 우리는 집으로 뛰어갔다. 아주 정말 재미있었다")


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
    return LH.get_host()


# ---------------------------------------------------------------- 세션
def _session_path(sid):
    return os.path.join(SESS_DIR, "%s.json" % sid)


def save_session(sid, res):
    payload = {
        "svg": res["svg"],
        "data": res["data"],
        "gate": res["gate"],
        "counts": res["counts"],
        "spec": res.get("spec") or {},
    }
    with open(_session_path(sid), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    latest = {"latest": sid}
    with open(INDEX_PATH, "w", encoding="utf-8") as fh:
        json.dump(latest, fh)


def load_session(sid):
    path = _session_path(sid)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def latest_session_id():
    if os.path.isfile(INDEX_PATH):
        with open(INDEX_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("latest")
    names = [n[:-5] for n in os.listdir(SESS_DIR) if n.endswith(".json") and n != "_index.json"]
    return sorted(names)[-1] if names else None


def session_count():
    return sum(1 for n in os.listdir(SESS_DIR)
               if n.endswith(".json") and n != "_index.json")


# ---------------------------------------------------------------- 파이프라인
def make_spec(text, drawn, review, extra=None):
    lines = max(1, len(text) // 18 + text.count("\n") + 1)
    spec = {"text": text, "indent": CA.layout_indent(text), "ncols": 20,
            "nrows": 2 * lines + 4, "double_space": True,
            "corrections": drawn, "review": review or {}}
    if extra:
        spec.update(extra)
    return spec


def run_pipeline(text, grade="초등 6학년", focus=None, llm_items=8, indirect=False):
    """규칙 계층 + (가능하면) LLM 계층 -> 게이트 -> SVG."""
    kiwi = get_kiwi()
    rules = CA.rule_layer(text, kiwi)
    llm, review, refused = [], {}, []
    errors = []
    for provider, host in LH.iter_hosts():
        try:
            llm, review, refused = CA.llm_layer(text, host, grade=grade,
                                                max_items=llm_items)
            errors = []
            break
        except Exception as exc:
            errors.append("%s: %s" % (provider, exc))
    if errors:
        refused = [{"kind": "-", "target": "", "reason": "",
                    "drop_reason": "LLM 계층 실패: " + " | ".join(errors)}]
    drawn, held, dropped = CA.assemble(text, rules, llm, refused=refused,
                                       focus=focus, max_items=CA.MAX_SHEET_ITEMS)
    if indirect:
        drawn = CA.to_indirect(drawn)
    spec = make_spec(text, drawn, review)
    built = WS.build(spec)
    return {"svg": built["svg"], "data": built["data"],
            "gate": CA.strip_span(dropped),
            "counts": {"rule": len(rules), "llm": len(llm), "drawn": len(drawn),
                       "held": len(held), "dropped": len(dropped)},
            "spec": spec}


# ---------------------------------------------------------------- 모델
class ChumsakIn(BaseModel):
    text: str
    grade: str = "초등 6학년"
    focus: list[str] | None = None
    llm_items: int = 8
    indirect: bool = False


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


# ---------------------------------------------------------------- 엔드포인트
@app.post("/api/chumsak")
def api_chumsak(body: ChumsakIn):
    text = (body.text or "").strip()
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


app.mount("/out", StaticFiles(directory=OUT), name="out")
app.mount("/", StaticFiles(directory=os.path.join(HERE, "web"), html=True), name="web")
