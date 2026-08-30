# -*- coding: utf-8 -*-
"""원고지 손글씨 사진 -> 칸 격자.

이 모듈의 한 문장: **OCR이 맞춤법을 고치면 첨삭기는 죽는다.**
학생이 쓴 '학교은'을 '학교는'으로 고쳐 넘기면 첨삭할 오류가 사라지고, 증상은
"맞춤법을 못 잡는다"로 나타나지만 원인은 규칙 계층이 아니라 여기다.

칸은 고정폭 문자열로 주고받는다. 한 행 = ncols 글자, 빈 칸 = 공백 한 자.
빈 칸을 버리면 문단 첫 칸을 비웠는지가 사라지고 원고지 형식 오류를 영영 못 잡는다.
"""
import base64
import re

NCOLS = 20
CONF_FLOOR = 0.85          # 이 아래는 교사에게 표시한다
MAX_PAGES = 12

OCR_SYSTEM = """당신은 한국어 원고지 사진을 읽는 문자 인식기다. 교정하지 않는다.

[가장 중요한 규칙]
맞춤법·띄어쓰기·문장부호를 절대 고치지 마라. 학생이 '학교은'이라고 썼으면 '학교은'으로
낸다. '되야'는 '되야'로, '느꼇다'는 '느꼇다'로 낸다. 틀린 것을 고쳐 주면 이 원고를
첨삭할 수 없게 된다. 당신의 일은 읽는 것이지 고치는 것이 아니다.

[무엇을 읽는가]
- 학생이 손으로 쓴 글자만 읽는다
- 인쇄된 원고지 격자선, 머리글(제목·이름·날짜 칸의 인쇄된 문구), 쪽번호는 읽지 않는다
- 이미 빨간 펜으로 그려진 교정부호가 있으면 글자로 읽지 말고 warnings에 적는다

[어떻게 내는가]
- 한 행을 정확히 %(ncols)d글자 문자열로 낸다. 한 칸에 한 글자다
- 빈 칸은 공백 한 자로 낸다. 빈 칸을 빼고 붙여 쓰지 마라
- 글자가 없는 뒷부분도 공백으로 채워 %(ncols)d글자를 맞춘다
- 읽을 수 없는 칸은 공백으로 두고 그 칸 번호를 uncertain에 넣는다. 추측해서 채우지 마라
- 문단이 새로 시작하는 행은 첫 칸을 비운다(원문이 그렇게 되어 있을 때만)
- conf는 그 행을 얼마나 확신하는지 0~1로 준다

[반드시]
submit_ocr 도구로만 답한다. 설명 문장을 쓰지 않는다.""" % {"ncols": NCOLS}

OCR_USER = "이 원고지 사진을 칸 단위로 읽어라. 고치지 말고 쓰인 그대로 낸다."


def ocr_tool_schema(ncols=NCOLS, max_rows=40):
    """구조화 출력 계약. 본문 텍스트 JSON은 파싱하지 않는다."""
    return {
        "name": "submit_ocr",
        "description": ("원고지 사진에서 읽은 칸 격자를 제출한다. cells는 정확히 %d글자 "
                        "문자열이고 빈 칸은 공백이다. 맞춤법을 고치지 않는다." % ncols),
        "input_schema": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array", "maxItems": max_rows,
                    "items": {
                        "type": "object",
                        "properties": {
                            "row": {"type": "integer", "minimum": 1},
                            "cells": {"type": "string",
                                      "description": "정확히 %d글자. 빈 칸은 공백." % ncols},
                            "conf": {"type": "number", "minimum": 0, "maximum": 1},
                            "uncertain": {"type": "array", "items": {"type": "integer"},
                                          "description": "읽지 못한 칸 번호(1부터)"},
                        },
                        "required": ["row", "cells"],
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["rows"],
        },
    }


# ---------------------------------------------------------------- 정규화
def normalize_rows(rows, ncols=NCOLS):
    """모델이 준 행을 고정폭으로 맞춘다. 길이가 어긋나면 경고로 남긴다.

    조용히 잘라 내면 칸이 밀린 채로 첨삭이 돌고, 부호가 엉뚱한 칸에 앉는다.
    """
    out, notes = [], []
    for i, r in enumerate(rows or []):
        raw = r.get("cells")
        if not isinstance(raw, str):
            continue
        cells = raw.replace("\t", " ").replace("　", " ")
        cells = cells.replace("\n", "").replace("\r", "")
        n = int(r.get("row") or (i + 1))
        if len(cells) > ncols:
            notes.append("%d행: %d칸으로 왔다. %d칸으로 잘랐다" % (n, len(cells), ncols))
            cells = cells[:ncols]
        elif len(cells) < ncols:
            cells = cells + " " * (ncols - len(cells))
        conf = r.get("conf")
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 1.0
        conf = min(1.0, max(0.0, conf))
        unc = [int(c) for c in (r.get("uncertain") or [])
               if isinstance(c, (int, float)) and 1 <= int(c) <= ncols]
        out.append({"row": n, "cells": cells, "conf": conf, "uncertain": unc})
    out.sort(key=lambda r: r["row"])
    return out, notes


def grid_to_text(pages, ncols=NCOLS):
    """칸 격자 -> 원문. 빈 칸과 문단 경계를 살린다.

    원고지에서 행 첫 칸이 비어 있는 것은 문단 시작을 뜻한다. 이어지는 행은 첫 칸부터
    채우기 때문이다(띄어쓰기가 행 끝에 걸리면 앞 행 끝에 붙인다). 그래서 첫 칸이 빈
    행 앞에서 문단을 나눈다. 이 정보를 버리면 문단 첫 칸 오류를 못 잡는다.
    """
    parts = []
    for page in pages or []:
        for row in page.get("rows") or []:
            cells = row.get("cells") or ""
            body = cells.rstrip(" ")
            if not body:
                continue
            if parts and cells.startswith(" "):
                parts.append("\n")
            parts.append(body)
    return "".join(parts)


def low_confidence(pages, floor=CONF_FLOOR, ncols=NCOLS):
    """교사가 먼저 짚어야 할 칸. 행 신뢰도가 낮거나 모델이 읽지 못한 칸."""
    out = []
    for page in pages or []:
        p = page.get("page") or 1
        for row in page.get("rows") or []:
            cells = row.get("cells") or ""
            for col in row.get("uncertain") or []:
                out.append({"page": p, "row": row.get("row"), "col": col,
                            "ch": cells[col - 1:col] if len(cells) >= col else "",
                            "conf": 0.0, "why": "읽지 못한 칸"})
            if row.get("conf", 1.0) < floor:
                out.append({"page": p, "row": row.get("row"), "col": None,
                            "ch": None, "conf": row.get("conf"),
                            "why": "행 전체 신뢰도가 낮다"})
    return out


# ---------------------------------------------------------------- 호출
def read_page(image_bytes, media_type, host, page=1, ncols=NCOLS, model=None):
    """이미지 한 장 -> 칸 격자 한 페이지. host는 llm_host가 만든 어댑터다."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    req = {
        "system": OCR_SYSTEM,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": OCR_USER}],
        "images": [{"media_type": media_type, "data": b64}],
        "tools": [ocr_tool_schema(ncols)],
        "tool_choice": {"type": "tool", "name": "submit_ocr"},
    }
    if model:
        req["model"] = model
    res = host.llm(req)
    tu = res.get("tool_use") or {}
    if tu.get("name") != "submit_ocr":
        raise RuntimeError("OCR 모델이 구조화 출력을 내지 않았다")
    data = tu.get("input") or {}
    rows, notes = normalize_rows(data.get("rows"), ncols)
    warns = [w for w in (data.get("warnings") or []) if isinstance(w, str)]
    return {"page": page, "ncols": ncols, "rows": rows}, warns + notes


MEDIA = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "webp": "image/webp", "gif": "image/gif", "heic": "image/heic"}


def media_type_of(filename, fallback=None):
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return MEDIA.get(ext) or fallback or "image/jpeg"


_NUM = re.compile(r"(\d+)")


def natural_key(name):
    """10.jpg가 2.jpg 앞에 오지 않게 한다. 사전순 정렬은 페이지를 뒤섞는다."""
    return [int(t) if t.isdigit() else t.lower() for t in _NUM.split(name or "")]
