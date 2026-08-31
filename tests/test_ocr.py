# -*- coding: utf-8 -*-
"""사진 입력 계층. 칸 보존, 교정 침묵, 확인 게이트를 본다.

이 세 가지가 이 계층의 존재 이유다. 하나라도 깨지면 첨삭이 조용히 틀린다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CHUMSAK_NO_LLM", "1")

import chumsak_app as CA          # noqa: E402
import ocr_wongoji as OCR         # noqa: E402


# ---------------------------------------------------------------- 칸 보존
def test_normalize_pads_short_row_and_warns():
    """짧은 행도 경고를 남긴다. 조용히 채우면 행 길이 위반률의 절반이 안 보인다."""
    rows, notes = OCR.normalize_rows([{"row": 1, "cells": "오늘"}], ncols=20)
    assert len(rows[0]["cells"]) == 20
    assert notes and "채웠다" in notes[0]


def test_exact_row_length_is_silent():
    """정확히 온 행은 경고가 없다. 위반률이 늘 100%가 되면 지표가 죽는다."""
    rows, notes = OCR.normalize_rows([{"row": 1, "cells": "가" * 20}], ncols=20)
    assert len(rows[0]["cells"]) == 20
    assert not notes


def test_overflow_characters_are_kept_not_discarded():
    """넘친 글자를 버리지 않는다. 실측에서 `곳입니다. 정`의 '정'이 이렇게 사라졌다."""
    rows, notes = OCR.normalize_rows(
        [{"row": 1, "cells": "사회성과 협동심을 기르는 곳입니다. 정"}], ncols=20)
    assert len(rows[0]["cells"]) == 20
    assert rows[0]["overflow"] == "정"
    assert notes and "교사 확인" in notes[0]


def test_overflow_reaches_the_teacher():
    rows, _ = OCR.normalize_rows(
        [{"row": 1, "cells": "사회성과 협동심을 기르는 곳입니다. 정"}], ncols=20)
    low = OCR.low_confidence([{"page": 1, "rows": rows}])
    assert any(c["ch"] == "정" and "넘쳐" in c["why"] for c in low)


def test_extra_space_is_dropped_before_any_character():
    """여분 공백이 있으면 글자 대신 공백을 버린다."""
    rows, notes = OCR.normalize_rows(
        [{"row": 1, "cells": "아니라, 여러 친구들과 함께 어울리며 "}], ncols=20)
    assert rows[0]["cells"] == "아니라, 여러 친구들과 함께 어울리며"
    assert "overflow" not in rows[0]
    assert "공백" in notes[0]


def test_blank_first_cell_survives_to_text():
    """문단 첫 칸을 비운 원고는 그 정보가 본문까지 살아야 한다.

    빈 칸을 버리면 layout_indent가 0을 내고 들여쓰기 오류를 영영 못 잡는다.
    """
    rows, _ = OCR.normalize_rows([{"row": 1, "cells": " 오늘 학교에 갔다."}], ncols=20)
    text = OCR.grid_to_text([{"page": 1, "rows": rows}])
    assert text.startswith(" ")
    assert CA.layout_indent(text) == 1


def test_missing_first_cell_is_an_error_the_engine_can_see():
    rows, _ = OCR.normalize_rows([{"row": 1, "cells": "오늘 학교에 갔다."}], ncols=20)
    text = OCR.grid_to_text([{"page": 1, "rows": rows}])
    assert CA.layout_indent(text) == 0
    assert any(c["kind"] == "indent" for c in CA.rule_indent(text))


def test_new_paragraph_from_indented_row():
    rows, _ = OCR.normalize_rows([
        {"row": 1, "cells": "오늘 비가 왔다."},
        {"row": 2, "cells": " 그래서 집에 있었다."},
    ], ncols=20)
    text = OCR.grid_to_text([{"page": 1, "rows": rows}])
    assert text.count("\n") == 1
    assert text.split("\n")[1].startswith(" ")


def test_empty_row_is_skipped():
    rows, _ = OCR.normalize_rows([
        {"row": 1, "cells": "비가 왔다."},
        {"row": 2, "cells": " " * 20},
    ], ncols=20)
    assert OCR.grid_to_text([{"page": 1, "rows": rows}]) == "비가 왔다."


def test_natural_page_order():
    names = ["10.jpg", "2.jpg", "1.jpg"]
    assert sorted(names, key=OCR.natural_key) == ["1.jpg", "2.jpg", "10.jpg"]


def test_low_confidence_lists_unread_cells():
    pages = [{"page": 1, "rows": [
        {"row": 1, "cells": "오 늘 학교", "conf": 0.99, "uncertain": [2]},
        {"row": 2, "cells": "비가 왔다", "conf": 0.40, "uncertain": []}]}]
    low = OCR.low_confidence(pages, floor=0.85)
    first = low[0]
    assert (first["page"], first["row"], first["col"]) == (1, 1, 2)
    assert any(c["col"] is None and c["row"] == 2 for c in low)


# ---------------------------------------------------------------- 교정 침묵
class SilentHost:
    """모델을 흉내 낸다. 학생이 틀리게 쓴 그대로 돌려준다."""

    def __init__(self, cells):
        self.cells = cells
        self.seen = None

    def reasoning_model(self):
        return "stub"

    def llm(self, req):
        self.seen = req
        return {"tool_use": {"name": "submit_ocr",
                             "input": {"rows": [{"row": i + 1, "cells": c, "conf": 0.95}
                                                for i, c in enumerate(self.cells)]}}}


def test_ocr_keeps_student_spelling_errors():
    """OCR이 맞춤법을 고치면 첨삭할 오류가 사라진다. 이것이 이 계층의 한 문장이다."""
    host = SilentHost([" 동생가 아이스크림를 먹었다"])
    page, _warns = OCR.read_page(b"fake", "image/png", host)
    text = OCR.grid_to_text([page])
    assert "동생가" in text and "아이스크림를" in text
    assert "동생이" not in text and "아이스크림을" not in text


def test_ocr_prompt_forbids_correction():
    """verbatim 규칙을 지우면 조용한 실패가 돌아온다. 프롬프트를 회귀로 묶어 둔다."""
    assert "고치지 마라" in OCR.OCR_SYSTEM
    assert "학교은" in OCR.OCR_SYSTEM          # 구체 예시가 있어야 모델이 따른다
    assert "손으로 쓴 글자만" in OCR.OCR_SYSTEM


def test_ocr_sends_image_and_forces_tool():
    host = SilentHost(["가나다"])
    OCR.read_page(b"binary", "image/jpeg", host)
    assert host.seen["images"][0]["media_type"] == "image/jpeg"
    assert host.seen["tool_choice"] == {"type": "tool", "name": "submit_ocr"}


def test_ocr_rejects_unstructured_answer():
    class Chatty:
        def llm(self, req):
            return {"text": '{"rows": []}', "tool_use": None}
    try:
        OCR.read_page(b"x", "image/png", Chatty())
    except RuntimeError as exc:
        assert "구조화" in str(exc)
    else:
        raise AssertionError("본문 텍스트 JSON을 받아들이면 안 된다")


# ---------------------------------------------------------------- 비전 어댑터
def test_each_adapter_carries_the_image():
    import llm_anthropic as A
    import llm_gemini as G
    import llm_openai as O
    msgs = [{"role": "user", "content": "읽어라"}]
    imgs = [{"media_type": "image/png", "data": "B64"}]
    a = A._with_images(msgs, imgs)[0]["content"]
    assert [b["type"] for b in a] == ["image", "text"]
    g = G._parts({"messages": msgs, "images": imgs})
    assert "inline_data" in g[0]
    o = O._with_images(msgs, imgs)[0]["content"]
    assert o[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # 이미지가 없으면 기존 경로가 그대로여야 한다
    assert A._with_images(msgs, None) == msgs
    assert O._with_images(msgs, None) == msgs


# ---------------------------------------------------------------- 확인 게이트
def _client():
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app), server


def _stage(server, cells):
    """비전 호출을 건너뛰고 인식 결과만 만들어 둔다."""
    import uuid
    rows, _ = OCR.normalize_rows(
        [{"row": i + 1, "cells": c, "conf": 0.9} for i, c in enumerate(cells)])
    oid = uuid.uuid4().hex[:12]
    server.save_ocr({"id": oid, "created": 0, "ncols": OCR.NCOLS,
                     "pages": [{"page": 1, "ncols": OCR.NCOLS, "rows": rows}],
                     "warnings": [], "confirmed": False, "text": None})
    return oid, [{"page": 1, "rows": [{"row": r["row"], "cells": r["cells"]} for r in rows]}]


def test_chumsak_refuses_unconfirmed_ocr():
    """확인 없이 첨삭하면 OCR 오인식이 학생 오류로 첨삭된다. 서버가 막는다."""
    cli, server = _client()
    oid, _pages = _stage(server, [" 동생가 아이스크림를 먹었다"])
    r = cli.post("/api/chumsak", json={"text": "아무거나", "ocr_id": oid})
    assert r.status_code == 409
    assert "확인하지 않은" in r.json()["error"]


def test_chumsak_refuses_unknown_ocr_id():
    cli, _server = _client()
    r = cli.post("/api/chumsak", json={"text": "x", "ocr_id": "deadbeef0000"})
    assert r.status_code == 404


def test_confirm_then_chumsak_uses_confirmed_text():
    cli, server = _client()
    oid, pages = _stage(server, [" 동생가 아이스크림를 먹었다"])

    c = cli.post("/api/ocr/confirm", json={"ocr_id": oid, "pages": pages})
    assert c.status_code == 200
    body = c.json()
    assert body["confirmed"] is True
    assert "동생가" in body["text"]           # 학생 오류가 살아 있다

    # 클라이언트가 엉뚱한 본문을 함께 보내도 서버는 확인된 본문만 쓴다.
    r = cli.post("/api/chumsak", json={"text": "전혀 다른 원고입니다", "ocr_id": oid})
    assert r.status_code == 200
    toks = "".join(cell["tok"] for cell in r.json()["data"]["cells"])
    assert "동생가" in toks
    assert "전혀" not in toks


def test_confirmed_ocr_text_keeps_indent_error_visible():
    """첫 칸을 비우지 않은 원고는 확인 뒤에도 들여쓰기 오류가 잡혀야 한다."""
    cli, server = _client()
    oid, pages = _stage(server, ["동생가 밥를 먹었다"])
    cli.post("/api/ocr/confirm", json={"ocr_id": oid, "pages": pages})
    r = cli.post("/api/chumsak", json={"ocr_id": oid})
    assert r.status_code == 200
    kinds = [c["kind"] for c in r.json()["data"]["corrections"]]
    assert "indent" in kinds


def test_confirm_rejects_empty_grid():
    cli, server = _client()
    oid, _pages = _stage(server, ["가나다"])
    r = cli.post("/api/ocr/confirm",
                 json={"ocr_id": oid, "pages": [{"page": 1, "rows": [
                     {"row": 1, "cells": " " * 20}]}]})
    assert r.status_code == 400


def test_text_input_path_still_works_without_ocr():
    """OCR이 죽어도 붙여넣기는 1급 입력이다."""
    cli, _server = _client()
    r = cli.post("/api/chumsak", json={"text": "동생가 밥를 먹었다"})
    assert r.status_code == 200
    assert r.json()["data"]["corrections"]


def test_ocr_record_holds_no_image():
    """학생 손글씨 사진은 개인정보다. 칸 격자만 남는다."""
    cli, server = _client()
    oid, _pages = _stage(server, ["가나다"])
    rec = server.load_ocr(oid)
    blob = str(rec)
    assert "image" not in blob and "base64" not in blob


# ---------------------------------------------------------------- 제목
def test_ocr_prompt_puts_title_outside_rows():
    """제목을 rows에 넣으면 본문 칸이 한 행 밀린다. 계약을 회귀로 묶는다."""
    assert "title로 낸다" in OCR.OCR_SYSTEM
    assert "칸 수 표시 숫자" in OCR.OCR_SYSTEM      # 여백의 100·200을 글자로 읽지 않게
    assert "title" in OCR.ocr_tool_schema(20)["input_schema"]["properties"]


def test_read_page_returns_title_separately():
    class TitleHost(SilentHost):
        def llm(self, req):
            self.seen = req
            return {"tool_use": {"name": "submit_ocr", "input": {
                "title": "  학교를 꼭 다녀야 하는가 ",
                "rows": [{"row": 1, "cells": c, "conf": 0.9}
                         for c in self.cells]}}}
    page, _w = OCR.read_page(b"x", "image/png", TitleHost([" 학교는 좋다"]))
    assert page["title"] == "학교를 꼭 다녀야 하는가"
    assert "학교를" not in OCR.grid_to_text([page])   # 본문에 섞이지 않는다


def test_confirm_carries_title_and_teacher_can_fix_it():
    cli, server = _client()
    oid, pages = _stage(server, [" 동생가 밥를 먹었다"])
    rec = server.load_ocr(oid)
    rec["title"] = "학교를 꼭 다녀야 하는가"
    server.save_ocr(rec)

    c = cli.post("/api/ocr/confirm", json={"ocr_id": oid, "pages": pages})
    assert c.json()["title"] == "학교를 꼭 다녀야 하는가"

    c2 = cli.post("/api/ocr/confirm",
                  json={"ocr_id": oid, "pages": pages, "title": "학교는 꼭 다녀야 하는가"})
    assert c2.json()["title"] == "학교는 꼭 다녀야 하는가"


def test_title_is_drawn_but_never_carries_a_mark():
    """제목은 문단이 아니다. 부호가 붙으면 rule_indent 오탐이 되살아난다."""
    cli, _server = _client()
    r = cli.post("/api/chumsak",
                 json={"text": " 동생가 밥를 먹었다", "title": "학교를 꼭 다녀야 하는가"})
    assert r.status_code == 200
    data = r.json()["data"]
    toks = "".join(c["tok"] for c in data["cells"])
    assert "학교를" in toks                                   # 지면에 있다
    # 제목 칸은 출처가 없다(src=None). 부호는 여기 앵커를 못 잡는다.
    title_rows = {c["r"] for c in data["cells"]
                  if c["tok"].strip() and c.get("src") is None}
    body_rows = {c["r"] for c in data["cells"] if c.get("src") is not None}
    assert title_rows and body_rows and max(title_rows) < min(body_rows)
    assert all(c["target"] not in ("학교를", "학교") for c in data["corrections"])


def test_no_llm_env_actually_stops_paid_calls():
    """get_host만 이 변수를 보던 시절, run_pipeline이 무시하고 호출을 내보냈다."""
    import llm_host as LH
    assert os.environ.get("CHUMSAK_NO_LLM")
    assert list(LH.iter_hosts()) == []


# ---------------------------------------------------------------- 행 이음매
def test_grid_to_text_reports_row_joins():
    """원고지는 행 끝의 띄어쓰기를 기록하지 않는다. 자리만 남긴다."""
    rows, _ = OCR.normalize_rows([
        {"row": 1, "cells": " 학교는 단순히 지식을 배우는 곳이"},
        {"row": 2, "cells": "아니라, 여러 친구들과 함께 어울리며"},
    ], ncols=20)
    text, joins = OCR.grid_to_text([{"page": 1, "rows": rows}], with_joins=True)
    assert "곳이아니라" in text
    assert joins == [19]
    assert text[19:22] == "아니라"


def test_paragraph_break_is_not_a_join():
    rows, _ = OCR.normalize_rows([
        {"row": 1, "cells": "비가 왔다."},
        {"row": 2, "cells": " 그래서 집에 갔다."},
    ], ncols=20)
    _text, joins = OCR.grid_to_text([{"page": 1, "rows": rows}], with_joins=True)
    assert joins == []          # 문단이 바뀌면 이음매가 아니다


def test_row_join_does_not_get_a_spacing_mark():
    """`곳이|아니라`는 학생이 규범대로 쓴 것이다. 띄움표를 달면 오탐이다."""
    import chumsak_app as CA
    text = " 학교는 단순히 지식을 배우는 곳이아니라, 여러 친구들과 함께 어울리며"
    fake = [CA.make("space", text, "곳이", 19,
                    reason="'곳이' 뒤를 띄어 써야 한다")]
    kept, dropped = CA.verify(text, fake)
    kept, joined = CA.drop_row_join_spacing(kept, [19])
    assert kept == [] and joined and "행 이음매" in joined[0]["drop_reason"]

    # 이음매가 아닌 자리의 띄움표는 그대로 산다
    kept2, _d = CA.verify(text, fake)
    kept2, joined2 = CA.drop_row_join_spacing(kept2, [5])
    assert len(kept2) == 1 and joined2 == []


def test_confirmed_ocr_suppresses_row_join_spacing_end_to_end():
    cli, server = _client()
    oid, pages = _stage(server, [" 학교는 단순히 지식을 배우는 곳이",
                                 "아니라, 여러 친구들과 함께 어울리며"])
    c = cli.post("/api/ocr/confirm", json={"ocr_id": oid, "pages": pages})
    assert c.json()["row_joins"] == [19]

    r = cli.post("/api/chumsak", json={"ocr_id": oid})
    assert r.status_code == 200
    body = r.json()
    assert not any(x["kind"] == "space" and x["target"] == "곳이"
                   for x in body["data"]["corrections"])
    assert any("행 이음매" in (g.get("drop_reason") or "") for g in body["gate"])
