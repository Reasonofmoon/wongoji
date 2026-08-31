# -*- coding: utf-8 -*-
"""원문 -> 칸 배치. 그림을 그리지 않는 순수 계산 층이다.

matplotlib에 기대지 않으므로 폰트 없는 환경에서도 돌고 테스트가 빠르다.
어느 글자가 몇 행 몇 칸에 앉는지는 여기서만 정해진다.
"""
import re
import textwrap

from wongoji_style import HANG

def tokenize(text, base=0):
    """(토큰, 원문 시작, 원문 끝). 숫자·로마자 소문자는 한 칸에 두 자."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isdigit():
            m = re.match(r"\d+", text[i:]).group()
            for k in range(0, len(m), 2):
                out.append((m[k:k + 2], base + i + k, base + i + min(k + 2, len(m))))
            i += len(m)
        elif re.match(r"[a-z]", c):
            m = re.match(r"[a-z]+", text[i:]).group()
            for k in range(0, len(m), 2):
                out.append((m[k:k + 2], base + i + k, base + i + min(k + 2, len(m))))
            i += len(m)
        else:
            out.append((c, base + i, base + i + 1))
            i += 1
    return out


def layout(blocks, ncols=20):
    """blocks: [None | (text, indent, align, base)] -> rows/src/hangs/wrap."""
    rows, src, hangs, wrap = [], [], {}, []
    for b in blocks:
        if b is None:
            rows.append([]); src.append([])
            continue
        text, indent, align, base = b
        toks = tokenize(text, base)
        if align in ("right", "center"):
            pad = (ncols - indent - len(toks)) if align == "right" \
                else max(0, (ncols - len(toks)) // 2)
            rows.append([" "] * pad + [t[0] for t in toks])
            src.append([None] * pad + [(t[1], t[2]) for t in toks])
            continue
        row, rsrc = [" "] * indent, [None] * indent
        j = 0
        while j < len(toks):
            if len(row) == ncols:
                if toks[j][0] in HANG:
                    hangs[len(rows)] = hangs.get(len(rows), "") + toks[j][0]
                    j += 1
                    continue
                if toks[j][0] == " ":
                    wrap.append(len(rows))
                    while j < len(toks) and toks[j][0] == " ":
                        j += 1
                rows.append(row); src.append(rsrc)
                row, rsrc = [], []
                continue
            row.append(toks[j][0]); rsrc.append((toks[j][1], toks[j][2]))
            j += 1
        rows.append(row); src.append(rsrc)
    return {"rows": rows, "src": src, "hangs": hangs, "wrap": wrap, "ncols": ncols}


def build_blocks(spec):
    """제목·소속·본문을 blocks로. 본문 원문 오프셋(base)을 함께 실어 보낸다."""
    blocks, body_start = [], 0
    if spec.get("title"):
        blocks += [None, (spec["title"], 0, "center", -1), None]
    for m in spec.get("meta", []):
        blocks.append((m, 2, "right", -1))
    if spec.get("title") or spec.get("meta"):
        blocks.append(None)
    text = spec.get("text", "")
    pos = 0
    for para in text.split("\n"):
        if not para.strip():
            blocks.append(None)
            pos += len(para) + 1
            continue
        blocks.append((para, spec.get("indent", 1), "left", pos))
        pos += len(para) + 1
    return blocks


def double_rows(lay):
    """줄마다 빈 줄을 앞에 넣어 첨삭 공간을 만든다. 행 인덱스는 2r+1로 밀린다."""
    rows, src = [[]], [[]]
    for r, row in enumerate(lay["rows"]):
        rows.append(row); src.append(lay["src"][r])
        rows.append([]); src.append([])
    return {"rows": rows, "src": src, "ncols": lay["ncols"],
            "hangs": {2 * r + 1: v for r, v in lay["hangs"].items()},
            "wrap": [2 * r + 1 for r in lay["wrap"]]}


def locate_span(lay, s, e):
    """원문 [s,e) 를 덮는 칸 목록 [(row, col), ...]."""
    hits = []
    for r, rsrc in enumerate(lay["src"]):
        for c, sp in enumerate(rsrc):
            if sp and sp[0] < e and sp[1] > s:
                hits.append((r, c))
    return hits


def locate_boundary(lay, pos):
    """원문 pos 직전 칸의 오른쪽 경계 -> (row, col). col은 경계의 왼쪽 칸 +1."""
    best = None
    for r, rsrc in enumerate(lay["src"]):
        for c, sp in enumerate(rsrc):
            if sp and sp[1] <= pos:
                if best is None or sp[1] > best[2]:
                    best = (r, c, sp[1])
    if best is None:
        return None
    return (best[0], best[1] + 1)


def resolve(spec_text, corr):
    """target/nth -> 원문 문자 범위."""
    t = corr.get("target")
    if t is None:
        return None
    nth, st, k = corr.get("nth", 0), 0, -1
    while True:
        k = spec_text.find(t, st)
        if k < 0:
            return None
        if nth == 0:
            return (k, k + len(t))
        nth -= 1
        st = k + 1


def clip_lines(text, width, max_lines):
    """줄바꿈 후 max_lines로 자르고, 잘렸으면 마지막 줄에 …를 붙인다."""
    lines = textwrap.wrap(text or "", width)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    kept[-1] = kept[-1].rstrip() + "\u2026"
    return kept
