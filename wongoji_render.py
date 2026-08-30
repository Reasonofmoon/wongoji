#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""원고지 격자 + 교정부호 오버레이 렌더러.

사용: python wongoji_render.py spec.json
spec.json 스키마는 SKILL.md 참조. 출력은 spec["out"] 경로(.png/.pdf).
"""
import json
import re
import sys
import textwrap

BODY_FONTS = ["NanumMyeongjo", "AppleMyungjo", "NanumGothic", "Apple SD Gothic Neo",
              "Malgun Gothic", "Noto Sans CJK KR", "DejaVu Sans"]
UI_FONTS = ["NanumGothic", "Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic",
            "Noto Sans CJK KR", "DejaVu Sans"]
RED = "#C0392B"
BLUE = "#1F4E79"
GRID = "#8A8A8A"
HANG = set(".,?!;:\u201d\u2019)]}\u300d\u300f")
BOUNDARY_KINDS = ("space", "insert", "punct", "newline", "joinline")
SPAN_KINDS = ("join", "delete", "replace", "swap", "indent", "outdent", "up", "down", "stet")
KIND_LABEL = {
    "space": "띄움표", "join": "붙임표", "insert": "넣음표", "punct": "부호 넣음표",
    "delete": "뺌표", "replace": "고침표", "swap": "자리 바꿈표", "newline": "줄 바꿈표",
    "joinline": "줄 이음표", "indent": "들여쓰기표", "outdent": "내어쓰기표",
    "up": "끌어 올림표", "down": "끌어 내림표", "stet": "되살림표",
}


# ---------------------------------------------------------------- fonts
def pick_fonts():
    import matplotlib.font_manager as fm
    have = {f.name for f in fm.fontManager.ttflist}
    body = next((f for f in BODY_FONTS if f in have), "DejaVu Sans")
    ui = next((f for f in UI_FONTS if f in have), "DejaVu Sans")
    return body, ui


# ---------------------------------------------------------------- layout
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


# ---------------------------------------------------------------- geometry
def geom(ncols=20, nrows=10, cw=1.0, ch=1.0, gap_after=10, gap=0.16):
    return {"ncols": ncols, "nrows": nrows, "cw": cw, "ch": ch,
            "gap_after": gap_after, "gap": gap}


def gx(g, col):
    extra = g["gap"] if (g["gap_after"] and col >= g["gap_after"]) else 0.0
    return col * g["cw"] + extra


def gy(g, row):
    return -row * g["ch"]


def gcx(g, col):
    return gx(g, col) + g["cw"] / 2


def gcy(g, row):
    return gy(g, row) - g["ch"] / 2


def draw_grid(ax, g, lw=0.6):
    from matplotlib.patches import Rectangle
    n, m = g["ncols"], g["nrows"]
    blocks = [(0, g["gap_after"]), (g["gap_after"], n)] if g["gap_after"] else [(0, n)]
    for c0, c1 in blocks:
        for r in range(m + 1):
            ax.plot([gx(g, c0), gx(g, c1 - 1) + g["cw"]], [gy(g, r)] * 2,
                    color=GRID, lw=lw, zorder=1)
        for c in range(c0, c1 + 1):
            xx = gx(g, c) if c < c1 else gx(g, c1 - 1) + g["cw"]
            ax.plot([xx] * 2, [gy(g, 0), gy(g, m)], color=GRID, lw=lw, zorder=1)
    ax.add_patch(Rectangle((gx(g, 0), gy(g, m)), gx(g, n - 1) + g["cw"] - gx(g, 0),
                           m * g["ch"], fill=False, ec="#333333", lw=1.4, zorder=2))


def fill_grid(ax, g, lay, font, size=12.5, color="#111111"):
    for r, row in enumerate(lay["rows"]):
        if r >= g["nrows"]:
            break
        for c, tok in enumerate(row):
            if c >= g["ncols"] or tok in (" ", "", None):
                continue
            s = size * (0.62 if len(tok) > 1 else 1.0)
            ax.text(gcx(g, c), gcy(g, r), tok, ha="center", va="center", fontsize=s,
                    color=color, zorder=4, fontfamily=font)
    for r, hp in lay["hangs"].items():
        if r < g["nrows"]:
            ax.text(gx(g, g["ncols"] - 1) + g["cw"] + 0.05, gcy(g, r) - 0.17, hp,
                    ha="left", va="center", fontsize=size, fontfamily=font, zorder=4)


# ---------------------------------------------------------------- marks
def _bezier(ax, x0, x1, y, h, color, lw, down=False):
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    w, sgn = x1 - x0, (-1 if down else 1)
    v = [(x0, y), (x0 + w * .25, y + sgn * h), (x1 - w * .25, y + sgn * h), (x1, y)]
    ax.add_patch(PathPatch(Path(v, [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]),
                           fc="none", ec=color, lw=lw, zorder=6))


def draw_mark(ax, g, kind, cells=None, boundary=None, text=None, font="DejaVu Sans",
              color=RED, lw=1.5, size=11, blanks=None):
    """교정부호 하나를 격자 위에 그린다. 반환: 번호표를 붙일 (x, y)."""
    from matplotlib.patches import FancyArrowPatch
    if kind in BOUNDARY_KINDS:
        r, c = boundary
        x, ytop = gx(g, min(c, g["ncols"])), gy(g, r)
        if kind == "newline":
            ybot = gy(g, r + 1) - 0.30
            ax.plot([x, x, x - 0.45], [ytop, ybot, ybot], color=color, lw=lw, zorder=6)
            ax.plot([x - .45, x - .30, x - .30], [ybot, ybot + .13, ybot - .13],
                    color=color, lw=lw, zorder=6)
            return (x + 0.50, ytop + 0.30)
        if kind == "joinline":
            ax.add_patch(FancyArrowPatch((x, gcy(g, r)), (gx(g, 0) - 0.10, gcy(g, r + 1)),
                                        connectionstyle="arc3,rad=-0.45", color=color,
                                        lw=lw, arrowstyle="-|>", mutation_scale=9, zorder=6))
            return (x + 0.45, gcy(g, r) + 0.35)
        s = 0.30
        ax.plot([x - s, x, x + s], [ytop + s * 1.5, ytop, ytop + s * 1.5],
                color=color, lw=lw, zorder=6, solid_capstyle="round")
        if kind in ("insert", "punct") and text:
            ax.text(x, ytop + 0.62, text, ha="center", va="bottom", color=color,
                    fontsize=size, zorder=6, fontfamily=font)
            return (x + 0.62, ytop + 0.72)
        return (x + 0.55, ytop + 0.50)

    if not cells:
        return None
    rr = sorted({r for r, _ in cells})
    r = rr[0]
    cs = sorted(c for rw, c in cells if rw == r)
    x0, x1 = gx(g, cs[0]), gx(g, cs[-1]) + g["cw"]
    ymid, ytop = gcy(g, r), gy(g, r)

    if kind == "join":
        gapc = [c for c in cs if blanks and blanks.get((r, c))]
        c0 = gapc[0] if gapc else cs[len(cs) // 2]
        a, b = gx(g, c0) - 0.14, gx(g, c0) + g["cw"] + 0.14
        _bezier(ax, a, b, ymid + 0.04, 0.30, color, lw)
        _bezier(ax, a, b, ymid + 0.02, 0.30, color, lw, down=True)
        return ((a + b) / 2, ytop + 0.55)
    if kind == "delete":
        for dy in (0.07, -0.07):
            ax.plot([x0 + .06, x1 - .06], [ymid + dy] * 2, color=color, lw=lw, zorder=6)
        xh = x1 - .06
        ax.plot([xh, xh + .22, xh + .22], [ymid, ymid, ytop + .30], color=color, lw=lw, zorder=6)
        ax.plot([xh + .10, xh + .22, xh + .34], [ytop + .15, ytop + .30, ytop + .15],
                color=color, lw=lw, zorder=6)
        return (xh + 0.90, ytop + 0.62)
    if kind == "replace":
        ax.plot([x0 + .06, x1 - .06], [ymid] * 2, color=color, lw=lw, zorder=6)
        xm = (x0 + x1) / 2
        ax.plot([xm] * 2, [ymid, ytop + .12], color=color, lw=lw, zorder=6)
        if text:
            ax.text(xm, ytop + .18, text, ha="center", va="bottom", color=color,
                    fontsize=size, zorder=6, fontfamily=font)
        return (xm + 0.80, ytop + 0.72)
    if kind == "swap":
        xm = (x0 + x1) / 2
        _bezier(ax, x0, xm, ymid + 0.05, 0.34, color, lw)
        _bezier(ax, xm, x1, ymid + 0.05, 0.34, color, lw, down=True)
        return (x1 + 0.45, ytop + 0.45)
    if kind in ("indent", "outdent"):
        d = 1 if kind == "indent" else -1
        xa = x0 - 0.58 if kind == "indent" else x0 + 0.60
        ax.plot([xa, xa + d * .45, xa + d * .45, xa], [ymid + .32, ymid + .32,
                ymid - .32, ymid - .32], color=color, lw=lw, zorder=6)
        return (xa - 0.57 if kind == "indent" else xa + 0.60, ymid)
    if kind in ("up", "down"):
        d = 1 if kind == "up" else -1
        xa, ya = x1 + 0.10, ymid
        ax.plot([xa, xa, xa + .50], [ya, ya + d * .55, ya + d * .55], color=color,
                lw=lw, zorder=6)
        ax.plot([xa + .34, xa + .50, xa + .34], [ya + d * .55 + .14, ya + d * .55,
                ya + d * .55 - .14], color=color, lw=lw, zorder=6)
        return (xa + 0.95, ya + d * 0.55)
    if kind == "stet":
        ax.plot([x0 + .06, x1 - .06], [ymid - 0.42] * 2, color=color, lw=lw,
                ls=(0, (1.2, 1.2)), zorder=6)
        ax.text((x0 + x1) / 2, ymid - 0.55, "살림", ha="center", va="top", color=color,
                fontsize=8.5, zorder=6, fontfamily=font)
        return (x1 + 0.45, ymid - 0.50)
    return None


# ---------------------------------------------------------------- render
# ---------------------------------------------------------------- 지면
SHEET_ROWS = 20        # 한 장에 그리는 행. double_space면 실제 원고 10행 = 200자 원고지
FIG_W = 9.6
PANEL_LINE = 0.17      # 범례·총평의 한 줄 높이(인치)
PAD_L, PAD_R = 1.15, 0.75   # 격자 좌우 여백(칸 단위). 왼쪽은 들여쓰기표 번호가 앉는다
PAD_T, PAD_B = 0.95, 0.25   # 위쪽은 부호가 행 밖으로 솟는 만큼


def sheet_inches(ncols, nrows, axes_w_in):
    """격자를 정비율로 그릴 때 필요한 축 높이(인치).

    축에 aspect="equal"이 걸려 있어 rect 높이를 임의로 주면 matplotlib이 축을 줄이고
    위아래에 슬랙을 남긴다. 그 슬랙이 제목과 격자 사이의 빈 띠로 보였다. 비율에서
    높이를 역산해 슬랙을 없앤다.
    """
    g = geom(ncols, nrows)
    xspan = gx(g, ncols - 1) + g["cw"] + PAD_R + PAD_L
    yspan = nrows * g["ch"] + PAD_T + PAD_B
    return axes_w_in * yspan / xspan


def paginate(lay, spec):
    """행을 원고지 장 단위로 끊는다. 반환: (장당 행 수, [(시작, 끝), ...])

    마지막 장도 온전한 한 장으로 그린다. 원고지는 남는 칸이 있는 채로 끝나는 것이
    정상이고, 빈 칸이 몇 개인지가 학생에게 정보다. 다만 **빈 장은 만들지 않는다** —
    호출측이 어림한 nrows를 그대로 믿어 열 줄 넘게 비어 있던 것이 문제였다.
    """
    per = int(spec.get("rows_per_sheet") or SHEET_ROWS)
    used = len(lay["rows"])
    pages = max(1, -(-used // per))
    return per, [(i * per, (i + 1) * per) for i in range(pages)]


def slice_lay(lay, a, b):
    """한 장 몫의 배치만 잘라 낸다. 행 인덱스를 0부터 다시 센다."""
    return {"rows": lay["rows"][a:b], "src": lay["src"][a:b], "ncols": lay["ncols"],
            "hangs": {r - a: v for r, v in lay["hangs"].items() if a <= r < b},
            "wrap": [r - a for r in lay["wrap"] if a <= r < b]}


def wrap_panel(corrs, review):
    """범례·총평 글줄을 미리 접는다. 접은 줄 수가 곧 지면 높이다."""
    legend = [clip_lines(c.get("reason", ""), 30, 3) for c in corrs]
    rv = [clip_lines((review or {}).get(k, ""), 30, 6) for k in ("good", "fix", "next")]
    return legend, rv


def panel_height(legend, rv, has_review):
    """범례와 총평 중 긴 쪽에 맞춘다(인치). 두 칸이 나란히 서므로 max다."""
    left = 0.66 + sum(max(1, len(w)) + 0.6 for w in legend) * PANEL_LINE
    right = (0.80 + sum(len(w) + 2.1 for w in rv) * PANEL_LINE) if has_review else 0.0
    return max(left, right, 0.8) + 0.30


def draw_sheet(fig, rect, g, sub, body, size, marks, page_no, pages):
    """한 장을 그린다. rect는 figure 비율 (left, bottom, width, height).

    부호는 행 0 위로도 올라가므로 위쪽에 여유를 둔다. 제목·쪽번호는 축이 아니라
    figure에 얹는다 — 축 안에 넣으면 격자 좌표계가 제목 높이만큼 왜곡된다.
    """
    from matplotlib.patches import Circle
    ax = fig.add_axes(rect)
    ax.set_axis_off()
    ax.set_aspect("equal")
    draw_grid(ax, g)
    fill_grid(ax, g, sub, body, size=size)
    blanks = {(r, c): True for r, row in enumerate(sub["rows"])
              for c, t in enumerate(row) if t == " "}
    drawn = []
    for n, corr, kind, cells, bnd in marks:
        if kind in BOUNDARY_KINDS:
            anchor = draw_mark(ax, g, kind, boundary=bnd, text=corr.get("text"), font=body)
        else:
            anchor = draw_mark(ax, g, kind, cells=cells, text=corr.get("text"),
                               font=body, blanks=blanks)
        if anchor:
            ax.add_patch(Circle((anchor[0], anchor[1]), 0.26, fc="white", ec=RED,
                                lw=1.0, zorder=8))
            ax.text(anchor[0], anchor[1], str(n), ha="center", va="center", fontsize=7.6,
                    color=RED, fontweight="bold", zorder=9)
        drawn.append((n, anchor))
    ax.set_xlim(-PAD_L, gx(g, g["ncols"] - 1) + g["cw"] + PAD_R)
    ax.set_ylim(gy(g, g["nrows"]) - PAD_B, PAD_T)
    if pages > 1:
        fig.text(rect[0] + rect[2], rect[1] + rect[3] - 0.006,
                 "%d / %d" % (page_no, pages), ha="right", va="top",
                 fontsize=8.2, color="#9a8d80")
    return drawn


def draw_panel(fig, rect, panel_h, resolved, legend, review, rv):
    """교정 내용과 총평. 축 안의 y를 **인치**로 두어 줄 간격이 어긋나지 않게 한다.

    전에는 줄 높이를 그림 인치로 계산해 놓고 축 비율 좌표에 그대로 썼다. 지면이
    길어질수록 실제 축은 짧아지는데 줄 간격은 그대로여서 글자가 겹쳤다.
    """
    from matplotlib.patches import FancyBboxPatch
    L = PANEL_LINE
    has_rv = bool(review)
    lw_frac = 0.505 if has_rv else 0.95
    lx = fig.add_axes([rect[0], rect[1], rect[2] * lw_frac, rect[3]])
    lx.set_axis_off(); lx.set_xlim(0, 1); lx.set_ylim(panel_h, 0)
    lx.text(0, 0.06, "교정 내용", fontsize=10.4, fontweight="bold", va="top")
    y = 0.58
    for n, corr, anchor in resolved:
        lx.text(0.012, y + L * 0.40, str(n), ha="center", va="center", fontsize=7.4,
                color=RED, fontweight="bold", zorder=3,
                bbox=dict(boxstyle="circle,pad=0.26", fc="white", ec=RED, lw=1.0))
        lab = KIND_LABEL.get(corr["kind"], corr["kind"])
        if anchor is None:
            lab += " (위치 확인 실패)"
        lx.text(0.045, y, lab, fontsize=9.0, fontweight="bold", va="top", ha="left")
        lines = legend[n - 1] if n - 1 < len(legend) else []
        lx.text(0.26, y, "\n".join(lines), fontsize=8.5, va="top", ha="left",
                color="#333333", linespacing=1.5)
        y += L * (max(1, len(lines)) + 0.6)
    if not has_rv:
        return
    cx = fig.add_axes([rect[0] + rect[2] * 0.545, rect[1], rect[2] * 0.455, rect[3]])
    cx.set_axis_off(); cx.set_xlim(0, 1); cx.set_ylim(panel_h, 0)
    cx.add_patch(FancyBboxPatch((0.012, 0.06), 0.976, panel_h - 0.16,
                 boxstyle="round,pad=0.006,rounding_size=0.02", fc="#FBF7F2",
                 ec="#C8A27A", lw=1.0, clip_on=False))
    cx.text(0.055, 0.20, "총평", fontsize=10.4, fontweight="bold", va="top")
    y = 0.72
    for k, head in enumerate(("잘한 점", "고칠 점", "다음에 해 볼 것")):
        cx.text(0.055, y, head, fontsize=9.2, fontweight="bold", va="top", color="#8B5E34")
        lines = rv[k] if k < len(rv) else []
        cx.text(0.055, y + L * 1.05, "\n".join(lines), fontsize=8.6, va="top",
                color="#333333", linespacing=1.55)
        y += L * (len(lines) + 2.1)


def render(spec):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    body, ui = pick_fonts()
    matplotlib.rcParams.update({"font.family": ui, "axes.unicode_minus": False,
                                "savefig.dpi": spec.get("dpi", 220)})
    ncols = spec.get("ncols", 20)
    lay = layout(build_blocks(spec), ncols)
    if spec.get("double_space"):
        lay = double_rows(lay)
    per, chunks = paginate(lay, spec)
    body_text = spec.get("text", "")
    corrs = spec.get("corrections", [])
    review = spec.get("review") or {}
    size = spec.get("font_size", 12.5)

    # 부호를 장별로 나눈다. 번호는 문서 전체에서 1부터 이어진다.
    per_page = [[] for _ in chunks]
    resolved_meta = []
    for n, corr in enumerate(corrs, 1):
        span = resolve(body_text, corr)
        kind = corr["kind"]
        row = None
        cells = bnd = None
        if span is not None:
            if kind in BOUNDARY_KINDS:
                bnd = locate_boundary(lay, span[1])
                row = bnd[0] if bnd else None
            else:
                cells = locate_span(lay, span[0], span[1])
                row = cells[0][0] if cells else None
        if row is None:
            resolved_meta.append((n, corr, None))
            continue
        p = min(row // per, len(chunks) - 1)
        a = chunks[p][0]
        if kind in BOUNDARY_KINDS:
            per_page[p].append((n, corr, kind, None, (bnd[0] - a, bnd[1])))
        else:
            per_page[p].append((n, corr, kind, [(r - a, c) for r, c in cells], None))
        resolved_meta.append((n, corr, p))

    legend, rv = wrap_panel(corrs, review)
    show_panel = bool(corrs or review)
    panel_h = panel_height(legend, rv, bool(review)) if show_panel else 0.0

    head1 = 0.80 if (spec.get("figure_title") or spec.get("caption")) else 0.22
    headn = 0.26
    sheet_h = sheet_inches(ncols, per, 0.91 * FIG_W)
    heads = [head1] + [headn] * (len(chunks) - 1)
    out = spec.get("out", "wongoji.png")
    is_pdf = str(out).lower().endswith(".pdf")

    anchors = {}

    def sheets_onto(fig, fig_h, pages_idx, first_head):
        top = 1.0 - 0.012
        for i, p in enumerate(pages_idx):
            head = first_head if i == 0 else headn
            top -= head / fig_h
            h = sheet_h / fig_h
            rect = [0.045, top - h, 0.91, h]
            got = draw_sheet(fig, rect, geom(ncols, per),
                             slice_lay(lay, *chunks[p]), body, size,
                             per_page[p], p + 1, len(chunks))
            for n, a in got:
                anchors[n] = a
            top -= h + 0.014
        return top

    def head_text(fig, fig_h):
        ttl = spec.get("figure_title")
        cap = spec.get("caption")
        if ttl:
            fig.text(0.045, 1.0 - 0.30 / fig_h, ttl, fontsize=12.5,
                     fontweight="bold", ha="left", va="top")
        if cap:
            fig.text(0.045, 1.0 - 0.60 / fig_h, cap, fontsize=8.6, color="#555555",
                     ha="left", va="top")

    if is_pdf:
        from matplotlib.backends.backend_pdf import PdfPages
        with PdfPages(out) as pdf:
            for p in range(len(chunks)):
                fh = (head1 if p == 0 else headn) + sheet_h + 0.35
                fig = plt.figure(figsize=(FIG_W, fh))
                if p == 0:
                    head_text(fig, fh)
                sheets_onto(fig, fh, [p], head1 if p == 0 else headn)
                pdf.savefig(fig, facecolor="white")
                plt.close(fig)
            if show_panel:
                resolved = [(n, c, anchors.get(n)) for n, c, _p in resolved_meta]
                fh = panel_h + 0.40
                fig = plt.figure(figsize=(FIG_W, fh))
                draw_panel(fig, [0.045, 0.22 / fh, 0.91, panel_h / fh], panel_h,
                           resolved, legend, review, rv)
                pdf.savefig(fig, facecolor="white")
                plt.close(fig)
    else:
        fig_h = sum(heads) + sheet_h * len(chunks) + 0.014 * len(chunks) + panel_h + 0.30
        fig = plt.figure(figsize=(FIG_W, fig_h))
        head_text(fig, fig_h)
        top = sheets_onto(fig, fig_h, list(range(len(chunks))), head1)
        if show_panel:
            resolved = [(n, c, anchors.get(n)) for n, c, _p in resolved_meta]
            ph = panel_h / fig_h
            draw_panel(fig, [0.045, max(0.008, top - ph - 0.012), 0.91, ph], panel_h,
                       resolved, legend, review, rv)
        fig.savefig(out, facecolor="white")
        plt.close(fig)

    unresolved = [n for n, _c, p in resolved_meta if p is None]
    return {"out": out, "rows_used": len(lay["rows"]), "rows_drawn": per * len(chunks),
            "pages": len(chunks), "corrections": len(corrs), "unresolved": unresolved,
            "sheet_rows": per,
            "font": body, "wrap_rows": lay["wrap"], "hangs": list(lay["hangs"].keys())}


def export_layout(spec):
    """그림 대신 칸 좌표와 부호 앵커를 JSON으로 낸다(브라우저 SVG 렌더링용)."""
    ncols = spec.get("ncols", 20)
    blocks = build_blocks(spec)
    lay = layout(blocks, ncols)
    if spec.get("double_space"):
        lay = double_rows(lay)
    per, chunks = paginate(lay, spec)
    nrows = per * len(chunks)
    body_text = spec.get("text", "")

    cells = []
    for r, row in enumerate(lay["rows"]):
        for c, tok in enumerate(row):
            if c >= ncols or tok in (" ", "", None):
                continue
            src = lay["src"][r][c] if c < len(lay["src"][r]) else None
            cells.append({"r": r, "c": c, "tok": tok, "src": list(src) if src else None})

    corrs = []
    for n, corr in enumerate(spec.get("corrections", []), 1):
        span = resolve(body_text, corr)
        item = {"n": n, "kind": corr["kind"],
                "label": KIND_LABEL.get(corr["kind"], corr["kind"]),
                "reason": corr.get("reason", ""), "layer": corr.get("layer", "표기"),
                "source": corr.get("source", "rule"),
                "severity": corr.get("severity", "보통"),
                "target": corr.get("target", ""), "nth": corr.get("nth", 0),
                "text": corr.get("text"), "state": corr.get("state", "pending"),
                "anchor": None}
        if span is not None:
            if corr["kind"] in BOUNDARY_KINDS:
                bnd = locate_boundary(lay, span[1])
                if bnd:
                    item["anchor"] = {"type": "boundary", "r": bnd[0], "c": bnd[1]}
            else:
                hit = locate_span(lay, span[0], span[1])
                if hit:
                    r0 = sorted({r for r, _ in hit})[0]
                    cs = sorted(c for rr, c in hit if rr == r0)
                    gapc = [c for c in cs if lay["rows"][r0][c] == " "]
                    item["anchor"] = {"type": "span", "r": r0, "c0": cs[0], "c1": cs[-1],
                                      "gap": gapc[0] if gapc else None}
        corrs.append(item)

    return {"grid": {"ncols": ncols, "nrows": nrows,
                     "gap_after": 10 if ncols > 10 else 0, "gap": 0.16},
            "cells": cells, "hangs": {str(k): v for k, v in lay["hangs"].items()},
            "wrap_rows": lay["wrap"], "corrections": corrs,
            "review": spec.get("review") or {},
            "meta": {"title": spec.get("title"), "figure_title": spec.get("figure_title"),
                     "caption": spec.get("caption"), "text": body_text,
                     "rows_used": len(lay["rows"])}}


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    if spec.get("mode") == "json":
        data = export_layout(spec)
        out = spec.get("out", "layout.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        print(json.dumps({"out": out, "cells": len(data["cells"]),
                          "corrections": len(data["corrections"]),
                          "unresolved": [c["n"] for c in data["corrections"]
                                         if c["anchor"] is None]}, ensure_ascii=False))
        return
    print(json.dumps(render(spec), ensure_ascii=False))


if __name__ == "__main__":
    main()
