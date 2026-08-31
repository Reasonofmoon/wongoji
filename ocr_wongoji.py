# -*- coding: utf-8 -*-
"""원고지 손글씨 사진 -> 칸 격자.

이 모듈의 한 문장: **OCR이 맞춤법을 고치면 첨삭기는 죽는다.**
학생이 쓴 '학교은'을 '학교는'으로 고쳐 넘기면 첨삭할 오류가 사라지고, 증상은
"맞춤법을 못 잡는다"로 나타나지만 원인은 규칙 계층이 아니라 여기다.

칸은 고정폭 문자열로 주고받는다. 한 행 = ncols 글자, 빈 칸 = 공백 한 자.
빈 칸을 버리면 문단 첫 칸을 비웠는지가 사라지고 원고지 형식 오류를 영영 못 잡는다.
"""
import base64
import io
import re

NCOLS = 20
CONF_FLOOR = 0.85          # 이 아래는 교사에게 표시한다
MAX_PAGES = 12
MAX_EDGE = 2000            # 긴 변 상한. 모델이 어차피 내부에서 줄인다

OCR_SYSTEM = """당신은 한국어 원고지 사진을 읽는 문자 인식기다. 교정하지 않는다.

[가장 중요한 규칙]
맞춤법·띄어쓰기·문장부호를 절대 고치지 마라. 학생이 '학교은'이라고 썼으면 '학교은'으로
낸다. '되야'는 '되야'로, '느꼇다'는 '느꼇다'로 낸다. 틀린 것을 고쳐 주면 이 원고를
첨삭할 수 없게 된다. 당신의 일은 읽는 것이지 고치는 것이 아니다.

[무엇을 읽는가]
- 학생이 손으로 쓴 글자만 읽는다
- 인쇄된 원고지 격자선, 인쇄된 라벨('주제'·'이름'·'날짜'·'첨삭지'), 칸 수 표시 숫자
  (100·200·300 같은 여백 숫자), 쪽번호는 읽지 않는다
- **제목 칸에 학생이 손으로 쓴 제목은 title로 낸다.** 인쇄된 '주제' 라벨은 빼고 학생이
  쓴 글자만. 제목을 rows에 넣지 마라 — 본문 칸이 한 행씩 밀린다
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
                "title": {"type": "string",
                          "description": ("제목 칸에 학생이 손으로 쓴 제목. 인쇄된 "
                                          "라벨은 빼고 쓴 그대로. 없으면 빈 문자열.")},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["rows"],
        },
    }


# ---------------------------------------------------------------- 정규화
_MULTISPACE = re.compile(r" {2,}")


def shrink_row(cells, ncols):
    """ncols를 넘겨 온 행을 줄인다. **글자보다 공백을 먼저 버린다.**

    모델은 행마다 공백을 하나씩 더 넣는 일이 잦다. 그때 오른쪽에서 그냥 잘라 내면
    행 끝의 실제 글자가 사라진다. 실측에서 `곳입니다. 정`의 `정`, `초등학교`의 `등`이
    이렇게 지워졌고, 본문에서 글자가 통째로 없어졌다. 조용한 데이터 파괴다.

    순서: 꼬리 공백 -> 겹공백(뒤에서부터) -> 그래도 남으면 자르고 세게 경고한다.
    """
    over = len(cells) - ncols
    if over <= 0:
        return cells.ljust(ncols), "그대로 두었다", ""

    tail = len(cells) - len(cells.rstrip(" "))
    cut = min(tail, over)
    if cut:
        cells = cells[:len(cells) - cut]
        over -= cut
    if over <= 0:
        return cells.ljust(ncols), "꼬리 공백 %d칸을 지웠다" % cut, ""

    # 겹공백을 뒤에서부터 한 칸씩 줄인다. 글자는 건드리지 않는다.
    spans = [m.span() for m in _MULTISPACE.finditer(cells)]
    for s0, s1 in reversed(spans):
        while over > 0 and s1 - s0 > 1:
            cells = cells[:s0] + cells[s0 + 1:s1] + cells[s1:]
            s1 -= 1
            over -= 1
        if over <= 0:
            break
    if over <= 0:
        return cells.ljust(ncols), "여분 공백을 지워 %d칸에 맞췄다" % ncols, ""

    # 여기까지 오면 글자가 넘친다. 홑공백을 지우면 띄어쓰기를 임의로 바꾸는 것이고,
    # 띄어쓰기는 오류 1순위 유형이라 추측할 자리가 아니다. 버리지 말고 넘긴다.
    overflow = cells[ncols:]
    return cells[:ncols], ("글자 %r가 넘쳤다 — 교사 확인 필요" % overflow), overflow


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
        overflow = ""
        raw_len = len(cells)
        if raw_len > ncols:
            cells, how, overflow = shrink_row(cells, ncols)
            notes.append("%d행: %d칸으로 왔다. %s" % (n, raw_len, how))
        elif raw_len < ncols:
            # 짧은 행도 남긴다. 조용히 채우면 행 길이 위반률의 절반이 보이지 않는다.
            notes.append("%d행: %d칸으로 왔다. %d칸까지 빈 칸으로 채웠다"
                         % (n, raw_len, ncols))
            cells = cells + " " * (ncols - raw_len)
        conf = r.get("conf")
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 1.0
        conf = min(1.0, max(0.0, conf))
        unc = [int(c) for c in (r.get("uncertain") or [])
               if isinstance(c, (int, float)) and 1 <= int(c) <= ncols]
        rec = {"row": n, "cells": cells, "conf": conf, "uncertain": unc}
        if overflow:
            # 넘친 글자를 버리지 않고 실어 보낸다. 확인 화면이 교사에게 보여 준다.
            rec["overflow"] = overflow
        out.append(rec)
    out.sort(key=lambda r: r["row"])
    return out, notes


def grid_to_text(pages, ncols=NCOLS, with_joins=False):
    """칸 격자 -> 원문. 빈 칸과 문단 경계를 살린다.

    원고지에서 행 첫 칸이 비어 있는 것은 문단 시작을 뜻한다. 이어지는 행은 첫 칸부터
    채우기 때문이다(띄어쓰기가 행 끝에 걸리면 앞 행 끝에 붙인다). 그래서 첫 칸이 빈
    행 앞에서 문단을 나눈다. 이 정보를 버리면 문단 첫 칸 오류를 못 잡는다.

    `with_joins=True`면 **행 이음매 오프셋**을 함께 낸다. 원고지는 행 끝의 띄어쓰기를
    기록하지 않는다 — 어절이 행 끝에서 끝나고 다음 행 첫 칸에서 새 어절이 시작해도
    공백을 쓰지 않는다. 그래서 이음매의 띄어쓰기는 **격자만으로 복원할 수 없다.**
    붙여 놓으면 `곳이아니라`가 되어 없던 띄어쓰기 오류가 생기고, 무조건 띄우면
    `아이스크 림를`처럼 이어지던 낱말이 갈라진다. 어느 쪽도 맞힐 수 없으므로 자리만
    남기고, 엔진이 그 자리에서는 띄어쓰기를 지적하지 않는다.
    """
    parts, joins, pos = [], [], 0
    for page in pages or []:
        for row in page.get("rows") or []:
            cells = row.get("cells") or ""
            body = cells.rstrip(" ")
            if not body:
                continue
            if parts and cells.startswith(" "):
                parts.append("\n")
                pos += 1
            elif parts:
                # 앞 행이 꽉 찬 채로 이어진다. 기록되지 않은 띄어쓰기 자리.
                joins.append(pos)
            parts.append(body)
            pos += len(body)
    text = "".join(parts)
    return (text, joins) if with_joins else text


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
            if row.get("overflow"):
                out.append({"page": p, "row": row.get("row"), "col": ncols,
                            "ch": row.get("overflow"), "conf": 0.0,
                            "why": "칸을 넘쳐 담기지 못한 글자"})
            if row.get("conf", 1.0) < floor:
                out.append({"page": p, "row": row.get("row"), "col": None,
                            "ch": None, "conf": row.get("conf"),
                            "why": "행 전체 신뢰도가 낮다"})
    return out


# ---------------------------------------------------------------- 전처리
def prepare_image(image_bytes, media_type=None, max_edge=MAX_EDGE):
    """모델에 보내기 전에 방향을 세우고 크기를 줄인다.

    **EXIF 회전을 여기서 적용한다.** 폰으로 세로로 찍은 사진은 픽셀이 가로로 저장되고
    회전은 EXIF 태그로만 표시된다. 태그를 존중하지 않는 디코더에 그대로 넘기면 모델이
    90도 누운 원고지를 받는다. 글자가 세로로 흐르니 거의 아무것도 못 읽는다. 증상은
    "OCR 성능이 나쁘다"인데 원인은 모델이 아니라 방향이다.

    실패하면 원본을 그대로 돌려준다. 전처리가 OCR 경로를 막지 않는다.
    """
    notes = []
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return image_bytes, media_type, ["Pillow가 없어 전처리를 건너뛰었다"]
    try:
        im = Image.open(io.BytesIO(image_bytes))
        before = im.size
        im = ImageOps.exif_transpose(im)
        if im.size != before:
            notes.append("EXIF 방향을 적용했다(%dx%d -> %dx%d)"
                         % (before[0], before[1], im.size[0], im.size[1]))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if max_edge and max(im.size) > max_edge:
            was = im.size
            im.thumbnail((max_edge, max_edge), Image.LANCZOS)
            notes.append("긴 변을 줄였다(%dx%d -> %dx%d)"
                         % (was[0], was[1], im.size[0], im.size[1]))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=92)
        return buf.getvalue(), "image/jpeg", notes
    except Exception as exc:
        return image_bytes, media_type, ["전처리를 건너뛰었다: %s" % exc]


# ---------------------------------------------------------------- 호출
def read_page(image_bytes, media_type, host, page=1, ncols=NCOLS, model=None,
              prepare=True):
    """이미지 한 장 -> 칸 격자 한 페이지. host는 llm_host가 만든 어댑터다."""
    prep_notes = []
    if prepare:
        image_bytes, media_type, prep_notes = prepare_image(image_bytes, media_type)
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
    title = data.get("title")
    title = title.strip() if isinstance(title, str) else ""
    out = {"page": page, "ncols": ncols, "rows": rows}
    if title:
        # 제목은 rows 바깥이다. 본문에 섞으면 첫 행이 밀리고, rule_indent가 제목을
        # 문단으로 보아 들여쓰기표를 잘못 단다.
        out["title"] = title
    return out, prep_notes + warns + notes


MEDIA = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
         "webp": "image/webp", "gif": "image/gif", "heic": "image/heic"}


def media_type_of(filename, fallback=None):
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return MEDIA.get(ext) or fallback or "image/jpeg"


_NUM = re.compile(r"(\d+)")


def natural_key(name):
    """10.jpg가 2.jpg 앞에 오지 않게 한다. 사전순 정렬은 페이지를 뒤섞는다."""
    return [int(t) if t.isdigit() else t.lower() for t in _NUM.split(name or "")]
