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
MAX_SHEET_ITEMS = 16


# ---------------------------------------------------------------- helpers
# ---------------------------------------------------------------- 학년
# 정본 학년 목록. 화면 <select>, samples.json, 골드 코퍼스가 모두 이 문자열을 쓴다.
# 코퍼스가 이미 '초등 N학년'·'중학교 N학년'을 쓰고 있어 그 어휘를 따랐다.
GRADES = (
    "초등 3학년", "초등 4학년", "초등 5학년", "초등 6학년",
    "중학교 1학년", "중학교 2학년", "중학교 3학년",
    "고등학교 1학년", "고등학교 2학년", "고등학교 3학년",
)
DEFAULT_GRADE = "초등 6학년"

# 학교급별 내용 첨삭 초점. 표기(O1~O10)는 학년과 무관하게 전수로 본다 —
# 맞춤법에 학년별 정답이 따로 있지 않다. 달라지는 것은 내용 층이다.
SCHOOL_GUIDE = {
    "초등": "문장을 끝까지 맺었는지, 낱말이 뜻에 맞는지, 겪은 일이 차례대로 놓였는지를 본다. "
            "글의 구조를 통째로 바꾸라고 하지 마라. 반복과 강조는 이 나이의 문체다.",
    "중학교": "문단이 한 화제로 묶였는지, 주어와 서술어가 호응하는지, 겹말과 상투어가 없는지를 본다. "
              "근거 없이 단정한 문장이 있으면 짚는다.",
    "고등학교": "주장과 근거가 이어지는지, 문단 사이 논리가 건너뛰지 않는지, 개념어를 일관되게 "
                "쓰는지를 본다. 문장 길이와 피동·명사화가 글을 흐리는 곳을 짚는다. "
                "맞춤법만 지적하고 끝내지 마라.",
}


def school_of(grade):
    """학년 문자열 -> 학교급. 모르는 값이면 기본 학년의 학교급으로 떨어진다."""
    for school in SCHOOL_GUIDE:
        if (grade or "").startswith(school):
            return school
    return "초등"


def grade_guide(grade):
    return SCHOOL_GUIDE[school_of(grade)]


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
         severity="보통", source="rule", confidence="certain"):
    item = {"kind": kind, "target": target, "nth": nth_of(text_all, target, pos),
            "reason": reason, "layer": layer, "severity": severity, "source": source,
            "confidence": confidence}
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
                out.append(make("space", text, text[s:e], e, confidence="uncertain",
                                reason="'%s' 뒤를 띄어 써야 한다" % text[s:e]))
        elif tag == "delete" and text[i1:i2] == " ":
            s = text.rfind(" ", 0, i1) + 1
            e = text.find(" ", i2)
            e = len(text) if e < 0 else e
            span = text[s:e]
            if " " in span:
                out.append(make("join", text, span, e, confidence="uncertain",
                                reason="'%s'는 붙여 써야 한다" % span.replace(" ", "")))
    return out


# 관형형 어미 뒤에 오면 띄어 써야 하는 말. NNB이거나, NNB로 안 잡히지만 의존적으로
# 쓰이는 NNG(정도·때·중·김·통)를 함께 본다.
DEP_NOUNS = frozenset(
    "것 거 걸 게 데 듯 수 시 때 터 뿐 만큼 지 줄 바 척 양 법 리 채 참 김 중 통 정도 나위"
    .split())


def rule_dependent_noun(text, kiwi):
    """관형형 어미(ETM) 바로 뒤의 의존명사를 붙여 썼으면 띄움표.

    **결정적 규칙이다.** `kiwi.space()`와 달리 근거가 품사에 있다. 실측 근거 문서의
    우선순위 1번이고, WS 오류의 가장 큰 덩이를 단일 규칙으로 덮는다.

    이것이 필요한 이유는 재현율만이 아니다. `kiwi.space()` 단독 제안은 철자가 틀린
    자리에서 형태소 분석이 무너지며 헛짚는다 — `채고로`(최고로) 뒤, `떡복기`(떡볶이)
    뒤, `놀이동산` 가운데. 결정적 규칙이 있으면 확신할 수 있는 것만 지면에 그리고
    나머지는 held로 보낼 수 있다.
    """
    out = []
    toks = kiwi.tokenize(text)
    for a, b in zip(toks, toks[1:]):
        if a.tag != "ETM":
            continue
        if not (b.tag == "NNB" or (b.tag.startswith("NN") and b.form in DEP_NOUNS)):
            continue
        gap = text[a.start + a.len:b.start]
        if gap:                       # 이미 띄어 썼으면 오류가 아니다
            continue
        st, en = word_at(text, b.start)
        if en <= st:
            continue
        out.append(make("space", text, text[st:en], en,
                        reason="'%s'는 앞말과 띄어 쓴다" % b.form,
                        severity="높음"))
    return out


def rule_particle_boundary(text, kiwi):
    """조사 바로 뒤에 체언·용언·부사가 붙어 있으면 어절 경계다. 띄움표.

    조사는 어절을 닫는다. 그 뒤에 새 낱말이 공백 없이 이어지면 두 어절을 붙여 쓴
    것이다 — `오늘의일기`, `나의재능`, `친구들과함께`, `밥을먹었다`.

    조사 연쇄(`학교에서는` = JKB + JX)와 조사 없는 합성어(`놀이동산에`)는 걸리지
    않는다. 근거가 품사에 있어서 철자 오류에 흔들리지 않는다.
    """
    out = []
    toks = kiwi.tokenize(text)
    for a, b in zip(toks, toks[1:]):
        if not a.tag.startswith("J"):
            continue
        if not (b.tag.startswith("NN") or b.tag.startswith("V")
                or b.tag.startswith("MA") or b.tag == "NP" or b.tag == "NR"):
            continue
        if text[a.start + a.len:b.start]:      # 이미 띄었으면 오류가 아니다
            continue
        st, en = word_at(text, b.start)
        if en <= st:
            continue
        out.append(make("space", text, text[st:en], en,
                        reason="조사 '%s' 뒤는 띄어 쓴다" % a.form, severity="높음"))
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


# 제목·이름 행의 끝에 오는 품사. 체언으로 끝나면 문장이 아니다.
HEADING_TAGS = frozenset(("NNG", "NNP", "NNB", "NP", "NR", "SN", "SL", "XSN"))
MAX_HEADING_LEN = 30
SENT_MARKS = ".?!\u2026"


def is_heading_line(line, kiwi):
    """원고지 머리 부분(제목·소속·이름) 한 줄인가.

    원고지에서 제목은 가운데, 소속·이름은 오른쪽에 앉는다. **둘 다 문단이 아니다.**
    문단으로 보면 들여쓰기표가 붙는데, 첫 칸을 비우는 규칙은 본문 문단의 것이다.

    판별은 마지막 형태소로 한다. 문장은 종결어미나 문장부호로 끝나고, 제목·이름은
    체언으로 끝난다. 길이나 줄 번호만으로 자르면 짧은 첫 문단을 제목으로 오인해
    진짜 오류를 놓친다.

    한계: `학교를 꼭 다녀야 하는가` 같은 의문형 제목은 EF로 끝나 잡지 못한다.
    사진 경로에서는 제목이 본문 바깥의 title 필드로 오므로 문제되지 않는다.
    """
    s = (line or "").strip()
    if not s or len(s) > MAX_HEADING_LEN:
        return False
    if any(ch in s for ch in SENT_MARKS):     # 종결부호가 있으면 문장이다
        return False
    toks = kiwi.tokenize(s)
    return bool(toks) and toks[-1].tag in HEADING_TAGS


def heading_lines(text, kiwi):
    """앞에서부터 이어지는 머리 줄의 개수. 최대 둘(제목 + 소속·이름)."""
    if kiwi is None:
        return 0
    lines = (text or "").split("\n")
    if len(lines) < 2:                        # 한 줄짜리 원고의 유일한 줄은 본문이다
        return 0
    n = 0
    for line in lines[:2]:
        if n == len(lines) - 1:               # 마지막 줄까지 머리로 보지 않는다
            break
        if not is_heading_line(line, kiwi):
            break
        n += 1
    return n


def rule_indent(text, kiwi=None):
    """문단 첫 칸을 비우지 않은 문단에 들여쓰기표를 붙인다.

    제목·소속 행은 건너뛴다. 원고지에서 그 줄들은 문단이 아니다.
    """
    out, pos = [], 0
    skip = heading_lines(text, kiwi)
    for i, para in enumerate(text.split("\n")):
        if i >= skip and para.strip() and not para.startswith(" "):
            first = para.split(" ")[0][:3]
            if first:
                out.append(make("indent", text, first, pos + len(first),
                                reason="문단 첫 칸을 비우지 않았다"))
        pos += len(para) + 1
    return out


def rule_layer(text, kiwi):
    """결정적 규칙은 그리고, kiwi.space() 단독 제안은 held로 보낸다.

    예전에는 kiwi 제안을 상한 4개까지 지면에 그렸다. 상한은 홍수를 가릴 뿐 오탐을
    없애지 못했고, 문서 순서로 잘라서 뒤쪽의 맞는 지적을 버리고 앞쪽 오탐을 남겼다.
    실측(초등 3학년 일기): 제안 11건 중 결정적으로 설명되는 것은 2건뿐이고, 나머지는
    `채고로`·`떡복기`·`놀이동산`처럼 철자 오류 자리에서 형태소 분석이 무너져 나온
    헛짚음이었다.

    오류유형 카탈로그의 오탐 억제 원칙 5가 이것이다 — 띄어쓰기 교정기는 맞춤법
    검사기가 아니다. 확신도가 낮은 제안은 지면에 그리지 않는다.
    """
    certain = dedupe(rule_dependent_noun(text, kiwi)
                     + rule_particle_boundary(text, kiwi))
    taken = {(c["kind"], c["target"], c["nth"]) for c in certain}
    loose = [c for c in rule_spacing(text, kiwi)
             if (c["kind"], c["target"], c["nth"]) not in taken]
    return certain + rule_sentence_end(text, kiwi) + rule_indent(text, kiwi) + loose


# ---------------------------------------------------------------- LLM 계층
LLM_SYSTEM = """당신은 한국어 작문을 첨삭하는 교사다. 원고지 교정부호로 표기와 내용을 함께 본다.
규칙 검사기가 띄어쓰기·마침표·첫 칸을 일부 잡지만, 놓친 오류는 당신이 해당 부호로 보완한다.
한 종류의 부호만 반복하지 마라. 이 글에 실제로 있는 오류 종류를 빠짐없이 올린다.
target은 본문에서 그대로 복사한다. 본문에 없는 문자열을 쓰면 부호를 그릴 수 없다.
한 항목은 짧게: span은 12자, 고침표는 8자, 넣음표는 4자를 넘기지 않는다."""

LLM_TASK = """다음은 {grade} 학생이 쓴 글이다. 교정 항목을 최대 {n}개 제출하라.
가능하면 서로 다른 부호를 섞어라. 띄움표만 내지 마라.

이 학년의 내용 첨삭에서 볼 것: {guide}

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


def llm_layer(text, host, grade=DEFAULT_GRADE, max_items=6, model=None):
    """host.llm 구조화 출력으로 내용 층 교정 항목과 총평을 얻는다."""
    schema = wongoji_llm_schema(max_items=max_items)
    res = host.llm({
        "messages": [{"role": "user",
                      "content": LLM_TASK.format(grade=grade, n=max_items, text=text,
                                                 guide=grade_guide(grade))}],
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


def drop_row_join_spacing(corrections, row_joins):
    """행 이음매에서는 띄어쓰기를 지적하지 않는다.

    원고지는 행 끝의 띄어쓰기를 **기록하지 않는다.** 어절이 행 끝에서 끝나고 다음 행
    첫 칸에서 새 어절이 시작해도 공백을 쓰지 않는 것이 관례다. 그래서 격자에서 복원한
    본문의 이음매는 `곳이아니라`처럼 붙어 있는데, 학생은 규범대로 쓴 것이다. 여기에
    띄움표를 달면 맞게 쓴 것을 틀렸다고 지적한다.

    반대로 무조건 띄우면 `아이스크|림를`처럼 행을 넘어 이어지던 낱말이 갈라진다.
    어느 쪽도 맞힐 수 없다. 기록되지 않은 것은 첨삭하지 않는다.
    """
    joins = set(row_joins or [])
    if not joins:
        return list(corrections), []
    keep, dropped = [], []
    for c in corrections:
        sp = c.get("_span")
        if sp and c["kind"] in ("space", "join"):
            at_join = (sp[1] in joins) if c["kind"] == "space" \
                else any(sp[0] < j < sp[1] for j in joins)
            if at_join:
                c = dict(c)
                c["drop_reason"] = "행 이음매다. 원고지는 이 자리의 띄어쓰기를 기록하지 않는다"
                dropped.append(c)
                continue
        keep.append(c)
    return keep, dropped


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
def layout_indent(text, kiwi=None):
    """원문 **첫 본문 문단**이 첫 칸을 비웠으면 1, 아니면 0.

    부호 유무로 indent를 바꾸지 않는다. 원문을 고쳐 그리면 들여쓰기 오류가 사라진다.

    제목·소속 행은 건너뛴다. 그 줄들은 문단이 아니므로 첫 칸이 차 있는 것이 정상이고,
    그것으로 본문 들여쓰기를 정하면 학생이 들여 쓴 원고를 지면에 붙여 그린다. 원문을
    잘못 재현하는 것이라 첨삭본으로서 틀리다. kiwi가 없으면 예전대로 첫 줄을 본다.
    """
    lines = (text or "").split("\n")
    para = lines[heading_lines(text, kiwi)] if lines else ""
    if para.strip() and not para.startswith(" "):
        return 0
    return 1


def assemble(text, rules, llm, refused=None, focus=None, max_items=MAX_SHEET_ITEMS,
             row_joins=None):
    """정규화·검증·겹침·초점. 서버와 라이브러리가 공유하는 유일한 조립기."""
    llm, bogus = normalize(text, llm)
    merged, dropped = verify(text, dedupe(list(rules) + list(llm)))
    dropped += list(refused or []) + bogus
    merged, joined = drop_row_join_spacing(merged, row_joins)
    dropped += joined
    merged, clashed = drop_overlaps(merged)
    dropped += clashed
    # 확신하지 못하는 제안은 지면에 그리지 않는다. 버리지도 않는다 — held로 남겨
    # 교사가 볼 수 있게 한다. 학생에게 틀린 지적을 주는 것이 안 주는 것보다 나쁘다.
    sure = [c for c in merged if c.get("confidence", "certain") != "uncertain"]
    unsure = [c for c in merged if c.get("confidence", "certain") == "uncertain"]
    drawn, held = focus_filter(sure, focus=focus, max_items=max_items)
    return drawn, held + unsure, dropped


def maybe_llm(text, host, grade=DEFAULT_GRADE, max_items=8, model=None):
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


def chumsak(text, host, kiwi, out="chumsak.png", grade=DEFAULT_GRADE, focus=None,
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
    spec = {"text": text, "indent": layout_indent(text, kiwi), "ncols": 20,
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
