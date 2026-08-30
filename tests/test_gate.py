# -*- coding: utf-8 -*-
"""게이트·규칙 계층 회귀. 형태소 분석기 없이 가짜 kiwi로 돈다."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import chumsak_app as CA  # noqa: E402


class Sent:
    def __init__(self, start, end):
        self.start, self.end = start, end


class FakeKiwi:
    def __init__(self, sents, spaced=None):
        self._sents = sents
        self._spaced = spaced

    def split_into_sents(self, text):
        return self._sents

    def space(self, text):
        return self._spaced if self._spaced is not None else text


def _item(kind, target, nth=0, text=None, reason="이유", source="llm",
          span=None, **kw):
    c = {"kind": kind, "target": target, "nth": nth, "reason": reason,
         "source": source, "layer": "내용"}
    if text is not None:
        c["text"] = text
    c.update(kw)
    if span is not None:
        c["_span"] = span
    return c


def test_verify_missing_target():
    keep, dropped = CA.verify("안녕하세요", [_item("delete", "없는말")])
    assert keep == []
    assert dropped[0]["drop_reason"].startswith("본문에서")


def test_verify_span_too_wide():
    text = "가" * 20
    keep, dropped = CA.verify(text, [_item("delete", text)])
    assert not keep
    assert "넓다" in dropped[0]["drop_reason"]


def test_verify_replace_whole_sentence():
    text = "아주 정말 재미있었다."
    c = _item("replace", text, text="정말 재미있었다.")
    keep, dropped = CA.verify(text, [c])
    assert not keep
    assert "통째" in dropped[0]["drop_reason"]


def test_verify_insert_too_long():
    text = "그래서 우리는 갔다"
    c = _item("insert", "그래서", text="x" * 43)
    keep, dropped = CA.verify(text, [c])
    assert not keep
    assert "칸에 넣을 수 없는" in dropped[0]["drop_reason"]


def test_verify_empty_reason():
    text = "어제 놀았다"
    keep, dropped = CA.verify(text, [_item("delete", "어제", reason="  ")])
    assert not keep
    assert "사유" in dropped[0]["drop_reason"]


def test_last_sentence_gets_punct():
    text = "어제 놀았다"
    kiwi = FakeKiwi([Sent(0, len(text))])
    out = CA.rule_sentence_end(text, kiwi)
    assert len(out) == 1
    assert out[0]["kind"] == "punct"
    assert out[0]["text"] == "."


def test_last_sentence_with_period_skipped():
    text = "어제 놀았다."
    kiwi = FakeKiwi([Sent(0, len(text))])
    assert CA.rule_sentence_end(text, kiwi) == []


def test_overlap_keeps_neighbor_different_kind():
    # 띄움표 1글자 vs 먼 마침표 제안: 긴 쪽 대비 겹침이 작다
    rules = [_item("space", "안", source="rule", span=(90, 91))]
    llm = [_item("punct", "안해도 된다는 장점도 있다", span=(90, 104), text=".")]
    for c in rules + llm:
        pass
    merged, dropped = CA.drop_overlaps(rules + llm)
    kinds = [c["kind"] for c in merged]
    assert "space" in kinds and "punct" in kinds
    assert dropped == []


def test_overlap_drops_same_locus_replace():
    rules = [_item("space", "친구와", source="rule", span=(6, 9))]
    llm = [_item("replace", "친구와같이", span=(6, 11), text="친구와 함께")]
    merged, dropped = CA.drop_overlaps(rules + llm)
    assert [c["kind"] for c in merged] == ["space"]
    assert dropped[0]["kind"] == "replace"


def test_assemble_is_single_gate():
    text = "어제 나는 친구와같이 놀았다."
    rules = [_item("space", "친구와", source="rule", nth=0, reason="띄어 쓴다")]
    llm = [_item("replace", "친구와같이", text="친구와 함께",
                 reason="구어체다")]
    drawn, held, dropped = CA.assemble(text, rules, llm, refused=[], max_items=12)
    assert any(c["kind"] == "space" for c in drawn)
    assert any("겹친다" in c.get("drop_reason", "") for c in dropped)


def test_host_none_skips_llm():
    empty = CA.maybe_llm("본문", None)
    assert empty == ([], {}, [])


def test_focus_filter_keeps_kind_diversity():
    items = []
    for i in range(10):
        items.append({"kind": "space", "target": "t%d" % i, "nth": i,
                      "reason": "띄움", "source": "rule", "severity": "보통"})
    items.append({"kind": "indent", "target": "어제", "nth": 0,
                  "reason": "첫 칸", "source": "rule", "severity": "보통"})
    items.append({"kind": "delete", "target": "아주", "nth": 0,
                  "reason": "겹말", "source": "llm", "severity": "보통"})
    items.append({"kind": "replace", "target": "갓다", "nth": 0, "text": "갔다",
                  "reason": "맞춤법", "source": "llm", "severity": "높음"})
    drawn, held = CA.focus_filter(items, max_items=6)
    kinds = {c["kind"] for c in drawn}
    assert "indent" in kinds
    assert "delete" in kinds
    assert "replace" in kinds
    assert sum(1 for c in drawn if c["kind"] == "space") < 6


def test_rule_layer_caps_space_marks():
    text = "가나다라마바사아자차카타"
    kiwi = FakeKiwi([Sent(0, len(text))],
                    spaced="가 나 다 라 마 바 사 아 자 차 카 타")
    items = CA.rule_layer(text, kiwi)
    n_space = sum(1 for c in items if c["kind"] == "space")
    assert n_space <= CA.MAX_RULE_SPACE
