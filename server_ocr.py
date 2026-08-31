# -*- coding: utf-8 -*-
"""사진 입력 라우터.

OCR 결과를 곧바로 첨삭에 넣지 않는다. `/api/ocr`는 본문 텍스트를 주지 않고,
`/api/ocr/confirm`을 지나야 본문이 나온다. 오인식과 학생 오류를 기계가 구분할 수 없어
확인 없이 첨삭하면 학생이 맞게 쓴 글자를 틀렸다고 배운다.
"""
import time
import uuid

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import llm_host as LH
import ocr_wongoji as OCR
from server_config import (MAX_IMAGE_BYTES, MAX_TEXT, MAX_TITLE,
                           MAX_UPLOAD_PAGES)
from server_store import load_ocr, save_ocr

router = APIRouter()


class OcrConfirmIn(BaseModel):
    ocr_id: str
    pages: list[dict]
    title: str | None = None       # 교사가 고친 제목. None이면 인식값을 그대로 쓴다


@router.post("/api/ocr")
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

    # 제목은 첫 장에서만 받는다. 뒷장의 제목 칸은 대개 비어 있다.
    title = next((p.get("title") for p in pages if p.get("title")), "")

    oid = uuid.uuid4().hex[:12]
    rec = {"id": oid, "created": time.time(), "ncols": OCR.NCOLS, "pages": pages,
           "title": title, "warnings": warnings + errors, "confirmed": False,
           "text": None}
    save_ocr(rec)
    return {"ocr_id": oid, "ncols": OCR.NCOLS, "pages": pages, "title": title,
            "low_conf": OCR.low_confidence(pages),
            "warnings": rec["warnings"], "confirmed": False}


@router.post("/api/ocr/confirm")
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
    title = body.title if body.title is not None else (rec.get("title") or "")
    title = title.strip()[:MAX_TITLE]
    # 행 이음매를 함께 남긴다. 원고지가 기록하지 않는 띄어쓰기 자리이고,
    # 엔진은 그 자리에서 띄어쓰기를 지적하지 않는다.
    text, row_joins = OCR.grid_to_text(pages, rec.get("ncols") or OCR.NCOLS,
                                       with_joins=True)
    if not text.strip():
        return JSONResponse({"error": "본문이 비어 있습니다."}, status_code=400)
    if len(text) > MAX_TEXT:
        return JSONResponse({"error": "본문이 너무 깁니다(%d자). %d자까지."
                             % (len(text), MAX_TEXT)}, status_code=400)
    rec.update({"pages": pages, "text": text, "title": title,
                "row_joins": row_joins, "confirmed": True,
                "confirmed_at": time.time()})
    save_ocr(rec)
    return {"ocr_id": rec["id"], "text": text, "title": title, "confirmed": True,
            "row_joins": row_joins, "chars": len(text)}
