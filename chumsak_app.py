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
from collections import defaultdict, deque

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
    kinds = list(LLM_ALLOWED)
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
                            "text": {"type": "string",
                                         "description": "insert·punct·replace는 필수. 넣을 글자 또는 고칠 글자."},
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
# 자동 첨삭에서 쓰는 부호. 되살림표만 교사 기각 전용이다.
LLM_ALLOWED = (
    "space", "join", "insert", "punct", "delete", "replace", "swap",
    "newline", "joinline", "indent", "outdent", "up", "down",
)
KIND_DRAW_ORDER = LLM_ALLOWED
MAX_RULE_SPACE = 4
MAX_SHEET_ITEMS = 16


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
    """종결부호 없이 끝난 문장에 부호 넣음표를 붙인다.

    마지막 문장도 본다. 글 전체가 마침표 없이 끝나면 그것이 가장 눈에 띄는 오류다.
    """
    out = []
    sents = list(kiwi.split_into_sents(text))
    for sent in sents:
        end = sent.end
        if end <= sent.start or end > len(text):
            continue
        last = text[end - 1]
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
    """띄움표는 상한을 둔다. kiwi.space()가 칸을 다 채우면 다른 부호가 지면에 못 앉는다."""
    spacing = rule_spacing(text, kiwi)
    joins = [c for c in spacing if c["kind"] == "join"]
    spaces = [c for c in spacing if c["kind"] == "space"][:MAX_RULE_SPACE]
    return joins + rule_sentence_end(text, kiwi) + rule_indent(text) + spaces


# ---------------------------------------------------------------- LLM 계층
LLM_SYSTEM = """당신은 한국어 작문을 첨삭하는 교사다. 원고지 교정부호로 표기와 내용을 함께 본다.
규칙 검사기가 띄어쓰기·마침표·첫 칸을 일부 잡지만, 놓친 오류는 당신이 해당 부호로 보완한다.
한 종류의 부호만 반복하지 마라. 이 글에 실제로 있는 오류 종류를 빠짐없이 올린다.
target은 본문에서 그대로 복사한다. 본문에 없는 문자열을 쓰면 부호를 그릴 수 없다.
한 항목은 짧게: span은 12자, 고침표는 8자, 넣음표는 4자를 넘기지 않는다."""

LLM_TASK = """다음은 {grade} 학생이 쓴 글이다. 교정 항목을 최대 {n}개 제출하라.
가능하면 서로 다른 부호를 섞어라. 띄움표만 내지 마라.

부호(kind) — 언제 쓰는지 — target — text
- space 띄움표: 붙여 쓴 곳을 띄운다. target=바로 앞 어절.
- join 붙임표: 잘못 띄운 두 어절. target=두 어절과 사이 공백.
- insert 넣음표: 빠진 글자. target=바로 앞 글자, text=넣을 글자(필수).
- punct 부호 넣음표: 빠진 문장부호. target=바로 앞 글자, text=.?!…
- delete 뺌표: 빼야 할 말. target=뺄 말만.
- replace 고침표: 틀린 글자(맞춤법·오탈자). target=원래 말, text=고칠 말(둘 다 필수, 8자 이하).
- swap 자리 바꿈표: 어절 순서. target=두 어절+공백.
- newline 줄 바꿈표: 문단을 나눌 때. target=바로 앞 어절.
- joinline 줄 이음표: 나뉜 줄을 이을 때. target=앞 줄 끝 어절.
- indent 들여쓰기표: 문단 첫 칸을 비우지 않음. target=문단 첫 어절.
- outdent 내어쓰기표: 잘못 들여 쓴 줄. target=그 줄 첫 어절.
- up 끌어 올림표: 아래 내용을 위로. target=올릴 범위.
- down 끌어 내림표: 위 내용을 아래로. target=내릴 범위.

오탈자·맞춤법은 replace로 잡고, text에 바른 표기를 반드시 넣는다.
잘못된 예: kind=replace, target=갓다, reason=맞춤법  (text가 없어 그리지 못함)
바른 예: kind=replace, target=갓다, text=갔다, reason='갔다'가 맞다, layer=표기
kind는 한 종류로 몰지 말고 최소 세 종류 이상을 섞어라.
layer는 표기는 "표기", 표현·구성은 "내용". 총평(review)은 잘한 점·고칠 점·다음에 해 볼 것.

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
        return [], {}, [{"kind": "-", "target": "", "reason": "",
                         "drop_reason": "LLM이 도구 호출을 반환하지 않았다"}]
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
        if c["kind"] in ("insert", "punct", "replace") and not str(rep).strip():
            c = dict(c); c["drop_reason"] = "넣을·고칠 글자(text)가 없어 부호를 그릴 수 없다"
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


def _spans_overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def drop_overlaps(corrections):
    """규칙 계층이 같은 자리를 이미 잡으면 LLM 항목을 뺀다.

    한 글자라도 겹친다고 버리지 않는다. 이웃한 다른 종류(띄움표 vs 먼 마침표)는
    지면에 같이 그릴 수 있다. 같은 종류, 같은 경계, 또는 긴 쪽 대비 절반 이상
    겹칠 때만 규칙 계층이 이긴다.
    """
    rules = [c for c in corrections if c.get("source") == "rule"]
    out, dropped = list(rules), []
    for c in corrections:
        if c.get("source") == "rule":
            continue
        s, e = c["_span"]
        clash = None
        for r in rules:
            rs, re = r["_span"]
            if not _spans_overlap((s, e), (rs, re)):
                continue
            if r["kind"] == c["kind"]:
                clash = r
                break
            if (r["kind"] in BOUNDARY_KINDS and c["kind"] in BOUNDARY_KINDS
                    and re == e):
                clash = r
                break
            ov = min(e, re) - max(s, rs)
            longer = max(e - s, re - rs)
            if longer and ov / longer >= 0.5:
                clash = r
                break
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


def focus_filter(corrections, focus=None, max_items=MAX_SHEET_ITEMS):
    """초점 첨삭. 한 종류가 지면을 채우지 않도록 부호 종류를 돌아가며 뽑는다."""
    if focus:
        pool = [c for c in corrections if c["kind"] in focus]
        held = [c for c in corrections if c["kind"] not in focus]
    else:
        pool, held = list(corrections), []
    order = {"높음": 0, "보통": 1, "낮음": 2}
    pool.sort(key=lambda c: (order.get(c.get("severity", "보통"), 1),
                             0 if c.get("source") == "rule" else 1))
    buckets = defaultdict(deque)
    for c in pool:
        buckets[c["kind"]].append(c)
    drawn = []
    while len(drawn) < max_items and any(buckets.values()):
        progressed = False
        for kind in KIND_DRAW_ORDER:
            if buckets[kind] and len(drawn) < max_items:
                drawn.append(buckets[kind].popleft())
                progressed = True
        if not progressed:
            for q in buckets.values():
                while q and len(drawn) < max_items:
                    drawn.append(q.popleft())
            break
    leftover = []
    for q in buckets.values():
        leftover.extend(q)
    return drawn, held + leftover


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
def layout_indent(text):
    """원문 첫 문단이 첫 칸을 비웠으면 1, 아니면 0.

    부호 유무로 indent를 바꾸지 않는다. 원문을 고쳐 그리면 들여쓰기 오류가 사라진다.
    """
    para = (text or "").split("\n")[0]
    if para.strip() and not para.startswith(" "):
        return 0
    return 1


def assemble(text, rules, llm, refused=None, focus=None, max_items=MAX_SHEET_ITEMS):
    """정규화·검증·겹침·초점. 서버와 라이브러리가 공유하는 유일한 조립기."""
    llm, bogus = normalize(text, llm)
    merged, dropped = verify(text, dedupe(list(rules) + list(llm)))
    dropped += list(refused or []) + bogus
    merged, clashed = drop_overlaps(merged)
    dropped += clashed
    drawn, held = focus_filter(merged, focus=focus, max_items=max_items)
    return drawn, held, dropped


def maybe_llm(text, host, grade="초등 6학년", max_items=8, model=None):
    """host가 없으면 빈 결과. LLM 실패는 호출측에서 잡는다."""
    if host is None:
        return [], {}, []
    return llm_layer(text, host, grade=grade, max_items=max_items, model=model)


def strip_span(corrections):
    """직렬화할 때 내부 _span을 뺀다."""
    out = []
    for c in corrections:
        item = {k: v for k, v in c.items() if k != "_span"}
        out.append(item)
    return out


def chumsak(text, host, kiwi, out="chumsak.png", grade="초등 6학년", focus=None,
            indirect=False, max_items=MAX_SHEET_ITEMS, llm_items=8, title=None, meta=None,
            rows_per_sheet=None, model=None, figure_title="첨삭본", caption=None):
    """원문 -> 첨삭본. 반환: {out, drawn, held, dropped, review, render}

    host가 None이면 규칙 계층만 돌고 총평은 비어 있다.
    """
    rules = rule_layer(text, kiwi)
    llm, review, refused = maybe_llm(text, host, grade=grade, max_items=llm_items,
                                     model=model)
    drawn, held, dropped = assemble(text, rules, llm, refused=refused,
                                    focus=focus, max_items=max_items)
    if indirect:
        drawn = to_indirect(drawn)
    spec = {"text": text, "indent": layout_indent(text), "ncols": 20,
            "double_space": True, "rows_per_sheet": rows_per_sheet,
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
