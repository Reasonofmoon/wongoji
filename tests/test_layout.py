# -*- coding: utf-8 -*-
"""칸 좌표 회귀. kiwipiepy 없이 돈다."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from wongoji_render import export_layout  # noqa: E402
from chumsak_app import layout_indent  # noqa: E402


def test_spec_example_all_marks_anchor():
    spec = json.load(open(os.path.join(ROOT, "examples", "spec_예시.json"),
                          encoding="utf-8"))
    data = export_layout(spec)
    unresolved = [c["n"] for c in data["corrections"] if not c.get("anchor")]
    assert unresolved == [], unresolved
    kinds = {c["n"]: (c["kind"], c["anchor"]["type"]) for c in data["corrections"]}
    assert kinds[1] == ("indent", "span")
    assert kinds[2] == ("space", "boundary")
    assert kinds[3] == ("join", "span")
    assert kinds[4] == ("punct", "boundary")
    assert kinds[5] == ("newline", "boundary")
    assert kinds[6] == ("delete", "span")


def test_layout_indent_follows_source():
    bare = "어제 나는 놀았다."
    padded = " 어제 나는 놀았다."
    assert layout_indent(bare) == 0
    assert layout_indent(padded) == 1
    assert layout_indent("") == 1


# ---------------------------------------------------------------- 지면 운용
def _long_spec(text=None):
    import chumsak_app as CA
    body = text or ("동생가 아이스크림를 먹었다 " * 30)   # 두 장을 넘기는 길이
    return {"text": body, "indent": CA.layout_indent(body), "ncols": 20,
            "double_space": True, "corrections": [],
            "review": {"good": "가" * 90, "fix": "나" * 90, "next": "다" * 90}}


def test_sheet_is_paginated_instead_of_one_long_page():
    """호출측이 어림한 nrows를 그대로 믿어 열 줄 넘게 비어 있던 문제를 막는다."""
    import wongoji_render as WR
    lay = WR.layout(WR.build_blocks(_long_spec()), 20)
    lay = WR.double_rows(lay)
    per, chunks = WR.paginate(lay, {})
    assert per == WR.SHEET_ROWS
    assert len(chunks) >= 2
    # 빈 장을 만들지 않는다: 마지막 장은 실제로 쓰인 행을 담는다
    assert chunks[-1][0] < len(lay["rows"])
    # 남는 행은 한 장 미만이다
    assert per * len(chunks) - len(lay["rows"]) < per


def test_paginate_never_returns_zero_pages():
    import wongoji_render as WR
    per, chunks = WR.paginate({"rows": [], "src": [], "ncols": 20,
                               "hangs": {}, "wrap": []}, {})
    assert len(chunks) == 1


def test_rows_per_sheet_is_honoured():
    import wongoji_render as WR
    lay = WR.double_rows(WR.layout(WR.build_blocks(_long_spec()), 20))
    per, chunks = WR.paginate(lay, {"rows_per_sheet": 10})
    assert per == 10
    assert len(chunks) == -(-len(lay["rows"]) // 10)


def test_export_layout_rows_match_paginated_sheets():
    """SVG와 PNG가 다른 행 수를 그리면 칸 좌표의 단일 출처가 깨진다."""
    import wongoji_render as WR
    spec = _long_spec()
    data = WR.export_layout(spec)
    lay = WR.double_rows(WR.layout(WR.build_blocks(spec), 20))
    per, chunks = WR.paginate(lay, spec)
    assert data["grid"]["nrows"] == per * len(chunks)


def test_panel_height_grows_with_content():
    """총평 줄이 늘면 지면도 늘어야 한다. 안 늘면 글자가 겹친다."""
    import wongoji_render as WR
    short = WR.panel_height([["한 줄"]], [["가"], ["나"], ["다"]], True)
    long_ = WR.panel_height([["한 줄"]], [["가"] * 6, ["나"] * 6, ["다"] * 6], True)
    assert long_ > short
    # 줄 하나가 늘 때마다 최소 한 줄 높이만큼은 늘어난다
    assert long_ - short >= WR.PANEL_LINE * 14
