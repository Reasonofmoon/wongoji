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


# ---------------------------------------------------------------- 학년
def test_select_options_match_the_canonical_grade_list():
    """화면 옵션과 엔진의 정본 목록이 갈라지면 학년이 조용히 안 먹는다.

    실제로 갈라져 있었다 — 화면은 '중등 1학년', 골드 코퍼스는 '중학교 1학년'.
    samples.json만 검사하는 테스트로는 잡히지 않았다.
    """
    import chumsak_app as CA
    html = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    block = re.search(r'<select id="grade">(.*?)</select>', html, re.S).group(1)
    opts = re.findall(r"<option[^>]*>([^<]+)</option>", block)
    assert opts == list(CA.GRADES)
    assert re.search(r'<option selected>([^<]+)</option>', block).group(1) == CA.DEFAULT_GRADE


def test_high_school_grades_are_selectable():
    import chumsak_app as CA
    assert "고등학교 3학년" in CA.GRADES
    assert [g for g in CA.GRADES if g.startswith("고등학교")] == [
        "고등학교 1학년", "고등학교 2학년", "고등학교 3학년"]


def test_corpus_grades_are_canonical():
    """골드 코퍼스도 같은 어휘를 쓴다. 다르면 학년별 지침이 엉뚱하게 붙는다."""
    import json
    import chumsak_app as CA
    for name in ("seed.jsonl", "showcase.jsonl"):
        path = os.path.join(ROOT, "tests", "corpus", name)
        for line in io.open(path, encoding="utf-8"):
            if line.strip():
                g = json.loads(line)["grade"]
                assert g in CA.GRADES, "%s의 학년 '%s'가 정본 목록에 없다" % (name, g)


def test_school_guide_differs_by_level():
    """학교급마다 내용 첨삭에서 볼 것이 다르다. 같으면 학년을 받는 뜻이 없다."""
    import chumsak_app as CA
    guides = {CA.grade_guide(g) for g in CA.GRADES}
    assert len(guides) == 3
    assert "주장과 근거" in CA.grade_guide("고등학교 2학년")
    assert "반복과 강조" in CA.grade_guide("초등 3학년")


def test_unknown_grade_is_refused_not_silently_defaulted():
    from fastapi.testclient import TestClient
    import server
    cli = TestClient(server.app)
    r = cli.post("/api/chumsak", json={"text": "동생가 밥를 먹었다", "grade": "중등 1학년"})
    assert r.status_code == 400
    assert "고등학교 3학년" in r.json()["grades"]


def test_every_grade_runs_end_to_end():
    import chumsak_app as CA
    from fastapi.testclient import TestClient
    import server
    cli = TestClient(server.app)
    for g in CA.GRADES:
        r = cli.post("/api/chumsak", json={"text": " 동생가 밥를 먹었다", "grade": g})
        assert r.status_code == 200, "%s에서 실패: %s" % (g, r.text)
