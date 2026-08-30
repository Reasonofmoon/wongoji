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
