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

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import chumsak_app as CA
import llm_host as LH
import ocr_wongoji as OCR
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
OCR_DIR = os.path.join(DATA_ROOT, "data", "ocr")
os.makedirs(OUT, exist_ok=True)
os.makedirs(SESS_DIR, exist_ok=True)
os.makedirs(OCR_DIR, exist_ok=True)


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
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_PAGES = 12
INDEX_PATH = os.path.join(SESS_DIR, "_index.json")

SAMPLES_PATH = os.path.join(HERE, "samples.json")


def load_samples():
    """앱에 들어 있는 시험용 원고. 정답 span은 담지 않는다 — 본문과 요약만."""
    if not os.path.isfile(SAMPLES_PATH):
        return []
    try:
        with open(SAMPLES_PATH, encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("samples") or []
    except (ValueError, OSError):
        return []


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


# ---------------------------------------------------------------- OCR 저장소
def ocr_path(oid):
    return os.path.join(OCR_DIR, "%s.json" % oid)


def save_ocr(rec):
    with open(ocr_path(rec["id"]), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False)
    return rec


def load_ocr(oid):
    """이미지는 저장하지 않는다. 칸 격자만 남는다."""
    if not oid or not str(oid).isalnum():
        return None
    path = ocr_path(oid)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- 모델
class ChumsakIn(BaseModel):
    text: str = ""
    grade: str = "초등 6학년"
    focus: list[str] | None = None
    llm_items: int = 8
    indirect: bool = False
    ocr_id: str | None = None


class OcrConfirmIn(BaseModel):
    ocr_id: str
    pages: list[dict]


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


@app.post("/api/ocr")
async def api_ocr(files: list[UploadFile] = File(...)):
    """원고지 사진 -> 칸 격자. **본문 텍스트는 여기서 주지 않는다.**

    교사가 /api/ocr/confirm 으로 칸을 확인해야 본문이 나온다. 확인을 건너뛰면
    OCR 오인식이 학생 오류로 첨삭된다. 그 구분은 기계가 할 수 없다.
    """
    if not files:
        return JSONResponse({"error": "이미지를 올려 주세요."}, status_code=400)
    if len(files) > MAX_UPLOAD_PAGES:
        return JSONResponse({"error": "한 번에 %d장까지 올릴 수 있습니다."
                             % MAX_UPLOAD_PAGES}, status_code=400)
    ordered = sorted(files, key=lambda f: OCR.natural_key(f.filename or ""))

    pages, warnings, errors = [], [], []
    for i, up in enumerate(ordered, 1):
        blob = await up.read()
        if not blob:
            continue
        if len(blob) > MAX_IMAGE_BYTES:
            errors.append("%s: 파일이 너무 큽니다(%.1fMB)"
                          % (up.filename, len(blob) / 1048576))
            continue
        media = OCR.media_type_of(up.filename, up.content_type)
        page, warns = None, []
        for provider, host in LH.iter_hosts():
            try:
                page, warns = OCR.read_page(blob, media, host, page=i)
                break
            except Exception as exc:
                errors.append("%s(%s): %s" % (up.filename, provider, exc))
        del blob                       # 이미지를 디스크에 남기지 않는다
        if page is None:
            continue
        pages.append(page)
        warnings.extend("%d쪽: %s" % (i, w) for w in warns)

    if not pages:
        return JSONResponse(
            {"error": "사진을 읽지 못했습니다. 붙여넣기로 입력할 수 있습니다.",
             "detail": errors[:3]}, status_code=502)

    oid = uuid.uuid4().hex[:12]
    rec = {"id": oid, "created": time.time(), "ncols": OCR.NCOLS, "pages": pages,
           "warnings": warnings + errors, "confirmed": False, "text": None}
    save_ocr(rec)
    return {"ocr_id": oid, "ncols": OCR.NCOLS, "pages": pages,
            "low_conf": OCR.low_confidence(pages),
            "warnings": rec["warnings"], "confirmed": False}


@app.post("/api/ocr/confirm")
def api_ocr_confirm(body: OcrConfirmIn):
    """교사가 고친 칸을 받아 본문을 확정한다. 여기서만 본문이 나온다."""
    rec = load_ocr(body.ocr_id)
    if rec is None:
        return JSONResponse({"error": "인식 결과를 찾을 수 없습니다."}, status_code=404)
    pages = []
    for i, page in enumerate(body.pages or [], 1):
        rows, _notes = OCR.normalize_rows(page.get("rows"), rec.get("ncols") or OCR.NCOLS)
        pages.append({"page": page.get("page") or i,
                      "ncols": rec.get("ncols") or OCR.NCOLS, "rows": rows})
    if not pages:
        return JSONResponse({"error": "확인할 칸이 없습니다."}, status_code=400)
    text = OCR.grid_to_text(pages)
    if not text.strip():
        return JSONResponse({"error": "본문이 비어 있습니다."}, status_code=400)
    if len(text) > MAX_TEXT:
        return JSONResponse({"error": "본문이 너무 깁니다(%d자). %d자까지."
                             % (len(text), MAX_TEXT)}, status_code=400)
    rec.update({"pages": pages, "text": text, "confirmed": True,
                "confirmed_at": time.time()})
    save_ocr(rec)
    return {"ocr_id": rec["id"], "text": text, "confirmed": True,
            "chars": len(text)}


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


WEB_DIR = os.path.join(HERE, "web")


@app.get("/")
def index_page():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


app.mount("/out", StaticFiles(directory=OUT), name="out")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
