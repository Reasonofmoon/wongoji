# -*- coding: utf-8 -*-
"""앱에 실린 샘플과 골드 코퍼스가 갈라지지 않았는지 본다.

본문이 어긋나면 화면에서 재는 것과 스크립트로 재는 것이 다른 글을 재게 된다.
중복을 없애는 대신 갈라짐을 게이트로 잡는다.
"""
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _samples():
    with io.open(os.path.join(ROOT, "samples.json"), encoding="utf-8") as fh:
        return {s["id"]: s for s in json.load(fh)["samples"]}


def _corpus():
    out = {}
    with io.open(os.path.join(ROOT, "tests", "corpus", "showcase.jsonl"),
                 encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                out[r["id"]] = r
    return out


def test_every_corpus_record_is_offered_in_the_app():
    missing = set(_corpus()) - set(_samples())
    assert not missing, "코퍼스에만 있고 앱에 없는 원고: %s" % missing


def test_sample_text_matches_corpus_text():
    samples, corpus = _samples(), _corpus()
    for rid, rec in corpus.items():
        assert samples[rid]["text"] == rec["text"], "%s 본문이 갈라졌다" % rid


def test_known_error_count_matches_gold():
    samples, corpus = _samples(), _corpus()
    for rid, rec in corpus.items():
        assert samples[rid]["known"] == len(rec["errors"]), \
            "%s 오류 건수가 코퍼스와 다르다" % rid


def test_samples_carry_no_answer_spans():
    """정답 자리를 앱에 실으면 사람이 스스로 판단할 기회가 사라진다."""
    blob = io.open(os.path.join(ROOT, "samples.json"), encoding="utf-8").read()
    assert "span" not in blob and "\"errors\"" not in blob


def test_control_sample_has_no_errors():
    """무오류 대조편이 없으면 정밀도를 눈으로도 잴 수 없다."""
    ctrl = [s for s in _samples().values() if s["known"] == 0]
    assert ctrl, "무오류 대조편이 목록에 없다"
    assert ctrl[0]["negatives"] > 0


def test_grade_matches_the_select_options():
    """학년 문자열이 <select> 옵션과 다르면 값이 조용히 안 바뀐다."""
    html = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    opts = set(re.findall(r"<option[^>]*>([^<]+)</option>", html))
    for s in _samples().values():
        assert s["grade"] in opts, "%s의 학년 '%s'가 옵션에 없다" % (s["id"], s["grade"])
