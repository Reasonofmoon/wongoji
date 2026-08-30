# -*- coding: utf-8 -*-
"""한국어 원고지 첨삭 엔진 프로토타입.

두 계층으로 교정 항목을 만든다.
  규칙 계층  — 띄어쓰기(kiwipiepy), 종결부호 누락, 문단 첫 칸. 결정적이고 설명 가능하다.
  LLM 계층   — 겹말·상투어·문체·문단 나누기·호응. 판단이 필요한 층.
두 계층의 결과를 합쳐 초점 첨삭 규칙으로 걸러내고, 원고지 격자에 부호를 그린다.

렌더링은 wongoji-chumsak 스킬의 wongoji_render()를 쓴다.
"""
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wongoji_render import render as render_figure   # noqa: E402


def wongoji_render(spec, out=None):
    """원고지 그림을 그린다(wongoji-chumsak 스킬의 렌더러와 같은 코드)."""
    if out is not None:
        spec = dict(spec)
        spec["out"] = out
    return render_figure(spec)


def wongoji_llm_schema(max_items=12):
    """LLM 구조화 출력용 도구 스키마. 스킬의 동명 헬퍼와 같은 계약."""
    kinds = sorted(KIND_ANCHOR)
    return {
        "name": "submit_chumsak",
        "description": ("원고지 첨삭 결과를 제출한다. target은 본문에서 그대로 복사한 "
                        "문자열이어야 하고, boundary 계열(space/insert/punct/newline/"
                        "joinline)은 부호를 놓을 자리 바로 앞 글자를, span 계열은 대상 "
                        "범위 전체를 target으로 준다."),
        "input_schema": {
            "type": "object",
            "properties": {
                "corrections": {
                    "type": "array", "maxItems": max_items,
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": kinds},
                            "target": {"type": "string"},
                            "nth": {"type": "integer", "minimum": 0},
                            "text": {"type": "string"},
                            "reason": {"type": "string"},
                            "layer": {"type": "string", "enum": ["표기", "내용"]},
                            "severity": {"type": "string",
                                         "enum": ["높음", "보통", "낮음"]},
                        },
                        "required": ["kind", "target", "reason", "layer"],
                    },
                },
                "review": {
                    "type": "object",
                    "properties": {"good": {"type": "string"}, "fix": {"type": "string"},
                                   "next": {"type": "string"}},
                    "required": ["good", "fix", "next"],
                },
            },
            "required": ["corrections", "review"],
        },
    }


KIND_ANCHOR = {
    "space": "boundary", "insert": "boundary", "punct": "boundary",
    "newline": "boundary", "joinline": "boundary",
    "join": "span", "delete": "span", "replace": "span", "swap": "span",
    "indent": "span", "outdent": "span", "up": "span", "down": "span", "stet": "span",
}

SENT_END = set(".?!\u2026\u201d")
BOUNDARY_KINDS = ("space", "insert", "punct", "newline", "joinline")
INDIRECT_BLANK = "\u25a1"          # 간접 첨삭에서 정답 대신 쓰는 빈 칸 기호
# LLM에 허용하는 부호. 되살림표·줄 이음표·끌어 올림/내림표·내어쓰기표는 교사가
# 지면을 편집할 때 쓰는 부호이므로 자동 첨삭에서 제외한다. 칭찬은 총평에만 쓴다.
LLM_ALLOWED = ("delete", "replace", "swap", "newline", "join", "insert", "space", "punct")


# ---------------------------------------------------------------- helpers
def nth_of(text, target, end):
    """target이 end에서 끝날 때 그것이 몇 번째 출현인지(0-based)."""
    start = end - len(target)
    n, st = 0, 0
    while True:
        k = text.find(target, st)
        if k < 0 or k >= start:
            return n
        n += 1
        st = k + 1


def word_at(text, pos):
    """pos 직전 어절(공백 사이 덩이)의 (시작, 끝)."""
    e = pos
    s = text.rfind(" ", 0, e) + 1
    return s, e


def make(kind, text_all, target, pos, replacement=None, reason="", layer="표기",
         severity="보통", source="rule"):
    item = {"kind": kind, "target": target, "nth": nth_of(text_all, target, pos),
            "reason": reason, "layer": layer, "severity": severity, "source": source}
    if replacement:
        item["text"] = replacement
    return item


# ---------------------------------------------------------------- 규칙 계층
def rule_spacing(text, kiwi):
    """kiwipiepy의 띄어쓰기 교정과 원문을 비교해 띄움표·붙임표 후보를 만든다."""
    fixed = kiwi.space(text)
    out = []
    sm = difflib.SequenceMatcher(None, text, fixed, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert" and fixed[j1:j2] == " ":
            s, e = word_at(text, i1)
            if e > s:
                out.append(make("space", text, text[s:e], e,
                                reason="'%s' 뒤를 띄어 써야 한다" % text[s:e]))
        elif tag == "delete" and text[i1:i2] == " ":
            s = text.rfind(" ", 0, i1) + 1
            e = text.find(" ", i2)
            e = len(text) if e < 0 else e
            span = text[s:e]
            if " " in span:
                out.append(make("join", text, span, e,
                                reason="'%s'는 붙여 써야 한다" % span.replace(" ", "")))
    return out


def rule_sentence_end(text, kiwi):
    """종결부호 없이 끝난 문장에 부호 넣음표를 붙인다."""
    out = []
    sents = list(kiwi.split_into_sents(text))
    for sent in sents[:-1] if sents else []:
        end = sent.end
        last = text[end - 1] if end <= len(text) else ""
        if last in SENT_END:
            continue
        tail = text[max(sent.start, end - 3):end].lstrip()
        if not tail:
            continue
        out.append(make("punct", text, tail, end, replacement=".",
                        reason="문장이 끝났는데 마침표가 없다", severity="높음"))
    return out


def rule_indent(text):
    """문단 첫 칸을 비우지 않은 문단에 들여쓰기표를 붙인다."""
    out, pos = [], 0
    for para in text.split("\n"):
        if para.strip() and not para.startswith(" "):
            first = para.split(" ")[0][:3]
            if first:
                out.append(make("indent", text, first, pos + len(first),
                                reason="문단 첫 칸을 비우지 않았다"))
        pos += len(para) + 1
    return out


def rule_layer(text, kiwi):
    return rule_spacing(text, kiwi) + rule_sentence_end(text, kiwi) + rule_indent(text)


# ---------------------------------------------------------------- LLM 계층
LLM_SYSTEM = """당신은 한국어 작문을 첨삭하는 교사다. 학생 글의 내용과 표현을 본다.
맞춤법·띄어쓰기·마침표 누락은 이미 규칙 검사기가 처리했으므로 중복해서 지적하지 않는다.
당신이 볼 것은 다음 층이다.
- 뜻이 겹치는 말, 상투적인 표현, 같은 말의 반복
- 문체 불일치(구어체와 문어체 혼용), 주어와 서술어의 호응
- 문단 나누기(장면·화제가 바뀌는 자리)
- 어절 순서가 어색한 곳
지적은 학생이 스스로 고칠 수 있을 만큼 구체적으로 쓰고, 칭찬은 무엇이 좋았는지 지목한다.
target은 반드시 본문에서 그대로 복사한다. 본문에 없는 문자열을 쓰면 부호를 그릴 수 없다."""

LLM_TASK = """다음은 {grade} 학생이 쓴 글이다. 교정 항목을 최대 {n}개 제출하라.

부호 선택 지침:
- delete(뺌표): 빼야 할 말. target에 뺄 말만.
- replace(고침표): 바꿀 말. target에 원래 말, text에 바꿀 말.
- swap(자리 바꿈표): 앞뒤 순서를 바꿀 두 어절을 공백까지 포함해 target에.
- newline(줄 바꿈표): 문단을 나눌 자리 **바로 앞** 어절을 target에.
- join(붙임표): 붙여야 할 두 어절을 공백까지 포함해 target에.
- insert(넣음표): 끼워 넣을 자리 **바로 앞** 글자를 target에, 넣을 글자를 text에.

layer는 모두 "내용"으로 한다. 총평(review)은 잘한 점·고칠 점·다음에 해 볼 것 세 칸으로 쓴다.

--- 본문 시작 ---
{text}
--- 본문 끝 ---"""


def llm_layer(text, host, grade="초등 6학년", max_items=6, model=None):
    """host.llm 구조화 출력으로 내용 층 교정 항목과 총평을 얻는다."""
    schema = wongoji_llm_schema(max_items=max_items)
    res = host.llm({
        "messages": [{"role": "user",
                      "content": LLM_TASK.format(grade=grade, n=max_items, text=text)}],
        "system": LLM_SYSTEM,
        "tools": [schema],
        "tool_choice": {"type": "tool", "name": schema["name"]},
        "max_tokens": 3000,
        "model": model or host.reasoning_model(),
    })
    tu = res.get("tool_use")
    blocks = [tu] if isinstance(tu, dict) else (tu or [])
    payload = None
    for blk in blocks:
        if isinstance(blk, dict) and blk.get("name") == schema["name"]:
            payload = blk.get("input")
    if payload is None:
        return [], {}, res
    out, refused = [], []
    for c in payload.get("corrections", []):
        c.setdefault("nth", 0)
        c["source"] = "llm"
        c.setdefault("layer", "내용")
        c.setdefault("severity", "보통")
        if c["kind"] not in LLM_ALLOWED:
            c["drop_reason"] = "%s는 교사가 지면 편집에 쓰는 부호다(LLM 사용 금지)" % c["kind"]
            refused.append(c)
        else:
            out.append(c)
    return out, payload.get("review", {}), refused


# ---------------------------------------------------------------- 병합·필터
MAX_SPAN = 12          # span 부호가 덮을 수 있는 최대 글자 수
MAX_REPLACE = 8        # 고침표로 바꿀 수 있는 최대 글자 수


def span_of(text, corr):
    """target/nth -> 원문 (시작, 끝). 못 찾으면 None."""
    t, nth, st = corr.get("target", ""), corr.get("nth", 0), 0
    if not t:
        return None
    while True:
        k = text.find(t, st)
        if k < 0:
            return None
        if nth == 0:
            return (k, k + len(t))
        nth -= 1
        st = k + 1


def verify(text, corrections):
    """target을 본문에서 찾을 수 있는지, 부호로 그릴 만한 크기인지 확인한다.

    지면에 그릴 수 없는 항목은 dropped로 빼고 reason에 이유를 적는다.
    한 문장을 통째로 바꾸라는 제안은 고침표가 아니라 총평에 들어갈 내용이다.
    """
    keep, dropped = [], []
    for c in corrections:
        t = c.get("target", "")
        sp = span_of(text, c)
        if not t or sp is None:
            c = dict(c); c["drop_reason"] = "본문에서 target을 찾지 못했다"
            dropped.append(c); continue
        if c["kind"] not in BOUNDARY_KINDS and len(t) > MAX_SPAN:
            c = dict(c); c["drop_reason"] = "부호가 덮을 범위가 너무 넓다(%d자)" % len(t)
            dropped.append(c); continue
        rep = c.get("text", "")
        if c["kind"] == "replace" and (len(t) > MAX_REPLACE or len(rep) > MAX_REPLACE):
            c = dict(c); c["drop_reason"] = "문장 통째 교체는 고침표로 표시하지 않는다"
            dropped.append(c); continue
        if c["kind"] in ("insert", "punct") and len(rep) > 4:
            c = dict(c); c["drop_reason"] = "칸에 넣을 수 없는 길이다(%d자)" % len(rep)
            dropped.append(c); continue
        if not c.get("reason", "").strip():
            c = dict(c); c["drop_reason"] = "사유가 비어 있어 학생에게 설명할 수 없다"
            dropped.append(c); continue
        c = dict(c); c["_span"] = sp
        keep.append(c)
    return keep, dropped


PUNCT_CHARS = set(".,?!;:\u2026")


def normalize(text, corrections):
    """LLM이 고른 부호를 교정부호 관례에 맞게 고치고, 헛짚은 항목을 뺀다.

    - 띄어쓰기만 다른 교체는 고침표가 아니라 붙임표다.
    - 문장부호를 넣는 것은 넣음표가 아니라 부호 넣음표다.
    - 이미 그 부호가 있는 자리에 또 넣으라는 항목은 뺀다(LLM 헛짚음).
    """
    out, dropped = [], []
    for c in corrections:
        c = dict(c)
        t, rep = c.get("target", ""), c.get("text", "")
        if c["kind"] == "replace" and rep and t.replace(" ", "") == rep.replace(" ", ""):
            c["kind"] = "join"
            c.pop("text", None)
        if c["kind"] == "insert" and rep and all(ch in PUNCT_CHARS for ch in rep):
            c["kind"] = "punct"
        if c["kind"] in ("punct", "insert") and rep:
            sp = span_of(text, c)
            nxt = text[sp[1]:sp[1] + len(rep)] if sp else ""
            if nxt == rep:
                c["drop_reason"] = "이미 '%s'가 있는 자리다" % rep
                dropped.append(c)
                continue
        out.append(c)
    return out, dropped


def drop_overlaps(corrections):
    """규칙 계층이 이미 잡은 자리를 LLM 항목이 다시 지적하면 LLM 쪽을 뺀다."""
    rules = [c for c in corrections if c.get("source") == "rule"]
    out, dropped = list(rules), []
    for c in corrections:
        if c.get("source") == "rule":
            continue
        s, e = c["_span"]
        clash = next((r for r in rules if r["_span"][0] < e and r["_span"][1] > s), None)
        if clash:
            c = dict(c)
            c["drop_reason"] = "규칙 계층의 '%s' 항목과 자리가 겹친다" % clash["kind"]
            dropped.append(c)
        else:
            out.append(c)
    return out, dropped


def dedupe(corrections):
    seen, out = set(), []
    for c in corrections:
        key = (c["kind"], c.get("target"), c.get("nth", 0))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def focus_filter(corrections, focus=None, max_items=12):
    """초점 첨삭: focus에 든 부호만 지면에 그리고 나머지는 집계만 한다."""
    if focus:
        drawn = [c for c in corrections if c["kind"] in focus]
        held = [c for c in corrections if c["kind"] not in focus]
    else:
        drawn, held = list(corrections), []
    order = {"높음": 0, "보통": 1, "낮음": 2}
    drawn.sort(key=lambda c: (order.get(c.get("severity", "보통"), 1),
                              0 if c.get("source") == "rule" else 1))
    if len(drawn) > max_items:
        held += drawn[max_items:]
        drawn = drawn[:max_items]
    return drawn, held


def to_indirect(corrections):
    """간접 첨삭: 정답을 써 주지 않고 자리와 종류만 표시한다."""
    out = []
    for c in corrections:
        c = dict(c)
        if c["kind"] in ("insert", "punct", "replace"):
            c["text"] = INDIRECT_BLANK
            c["reason"] = c.get("reason", "") + " (무엇이 들어갈지 찾아 쓰기)"
        out.append(c)
    return out


# ---------------------------------------------------------------- 파이프라인
def chumsak(text, host, kiwi, out="chumsak.png", grade="초등 6학년", focus=None,
            indirect=False, max_items=12, llm_items=6, title=None, meta=None,
            nrows=None, model=None, figure_title="첨삭본", caption=None):
    """원문 -> 첨삭본. 반환: {out, drawn, held, dropped, review, render}"""
    rules = rule_layer(text, kiwi)
    llm, review, refused = llm_layer(text, host, grade=grade, max_items=llm_items,
                                     model=model)
    llm, bogus = normalize(text, llm)
    merged, dropped = verify(text, dedupe(rules + llm))
    dropped += refused + bogus
    merged, clashed = drop_overlaps(merged)
    dropped += clashed
    drawn, held = focus_filter(merged, focus=focus, max_items=max_items)
    if indirect:
        drawn = to_indirect(drawn)
    indent = 0 if any(c["kind"] == "indent" for c in drawn) else 1
    lines = max(1, len(text) // 18 + text.count("\n") + 1)
    spec = {"text": text, "indent": indent, "ncols": 20,
            "nrows": nrows or (2 * lines + 4), "double_space": True,
            "corrections": drawn, "review": review, "out": out,
            "figure_title": figure_title,
            "caption": caption or ("규칙 계층 %d건 + LLM 계층 %d건 → 지면에 %d건"
                                   % (len(rules), len(llm), len(drawn)))}
    if title:
        spec["title"] = title
    if meta:
        spec["meta"] = meta
    info = wongoji_render(spec)
    return {"out": info["out"], "render": info, "drawn": drawn, "held": held,
            "dropped": dropped, "review": review,
            "counts": {"rule": len(rules), "llm": len(llm), "drawn": len(drawn),
                       "held": len(held), "dropped": len(dropped)}}
