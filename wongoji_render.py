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
def render(spec):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, FancyBboxPatch

    body, ui = pick_fonts()
    matplotlib.rcParams.update({"font.family": ui, "axes.unicode_minus": False,
                                "savefig.dpi": spec.get("dpi", 220)})
    ncols = spec.get("ncols", 20)
    blocks = build_blocks(spec)
    lay = layout(blocks, ncols)
    if spec.get("double_space"):
        lay = double_rows(lay)
    nrows = spec.get("nrows") or max(10, len(lay["rows"]) + 1)
    g = geom(ncols, nrows)

    corrs = spec.get("corrections", [])
    review = spec.get("review") or {}
    show_panel = bool(corrs or review)
    body_text = spec.get("text", "")

    # 범례·총평의 줄 수를 먼저 세어 그림 높이를 정한다(글자 넘침 방지)
    legend_wrapped, review_wrapped = [], []
    if show_panel:
        for corr in corrs:
            legend_wrapped.append(clip_lines(corr.get("reason", ""), 30, 3))
        for key in ("good", "fix", "next"):
            review_wrapped.append(clip_lines(review.get(key, ""), 26, 6))
    legend_lines = sum(1 + len(w) + 0.35 for w in legend_wrapped)
    review_lines = sum(1.4 + len(w) + 0.9 for w in review_wrapped)
    panel_h = (max(legend_lines, review_lines) * 0.175 + 0.75) if show_panel else 0.35
    sheet_h = 0.46 * nrows + 1.0
    fig_h = sheet_h + panel_h
    fig = plt.figure(figsize=(9.6, fig_h))
    sheet_frac = (0.46 * nrows) / fig_h
    ax = fig.add_axes([0.035, 1 - sheet_frac - 0.055, 0.93, sheet_frac])
    ax.set_axis_off(); ax.set_aspect("equal")
    draw_grid(ax, g)
    fill_grid(ax, g, lay, body, size=spec.get("font_size", 12.5))

    blanks = {(r, c): True for r, row in enumerate(lay["rows"])
              for c, t in enumerate(row) if t == " "}
    resolved = []
    for n, corr in enumerate(corrs, 1):
        span = resolve(body_text, corr)
        if span is None:
            resolved.append((n, corr, None))
            continue
        kind = corr["kind"]
        if kind in BOUNDARY_KINDS:
            bnd = locate_boundary(lay, span[1])
            anchor = draw_mark(ax, g, kind, boundary=bnd, text=corr.get("text"),
                               font=body) if bnd else None
        else:
            cells = locate_span(lay, span[0], span[1])
            anchor = draw_mark(ax, g, kind, cells=cells, text=corr.get("text"),
                               font=body, blanks=blanks)
        if anchor:
            ax.add_patch(Circle((anchor[0], anchor[1]), 0.26, fc="white", ec=RED,
                                lw=1.0, zorder=8))
            ax.text(anchor[0], anchor[1], str(n), ha="center", va="center", fontsize=7.6,
                    color=RED, fontweight="bold", zorder=9)
        resolved.append((n, corr, anchor))

    ax.set_xlim(-1.9, gx(g, ncols - 1) + g["cw"] + 0.9)
    ax.set_ylim(gy(g, nrows) - 0.5, 1.9)
    ttl = spec.get("figure_title")
    if ttl:
        ax.text(-1.9, 1.30, ttl, fontsize=12.5, fontweight="bold", ha="left", va="bottom")
    cap = spec.get("caption")
    if cap:
        ax.text(-1.9, 0.55, cap, fontsize=8.6, color="#555555", ha="left", va="bottom")

    if show_panel:
        panel_bottom, panel_top = 0.02, 1 - sheet_frac - 0.075
        ph = panel_top - panel_bottom
        line = 0.175 / panel_h          # 한 줄 높이(패널 축 비율)
        pw = 0.50 if review else 0.93
        lx = fig.add_axes([0.035, panel_bottom, pw, ph])
        lx.set_axis_off(); lx.set_xlim(0, 1); lx.set_ylim(0, 1)
        lx.text(0, 1.0, "교정 내용", fontsize=10.4, fontweight="bold", va="top")
        y = 1.0 - 1.5 * line
        for n, corr, anchor in resolved:
            lx.add_patch(FancyBboxPatch((0.002, y - line * 0.85), 0.038, 0.038,
                         boxstyle="circle,pad=0.002", fc="white", ec=RED, lw=1.0,
                         transform=lx.transAxes, clip_on=False))
            lx.text(0.021, y - line * 0.42, str(n), ha="center", va="center", fontsize=7.6,
                    color=RED, fontweight="bold")
            lab = KIND_LABEL.get(corr["kind"], corr["kind"])
            if anchor is None:
                lab += " (위치 확인 실패)"
            lx.text(0.055, y, lab, fontsize=9.0, fontweight="bold", va="top", ha="left")
            body_lines = legend_wrapped[n - 1] if n - 1 < len(legend_wrapped) else []
            lx.text(0.30, y, "\n".join(body_lines), fontsize=8.5, va="top", ha="left",
                    color="#333333", linespacing=1.45)
            y -= line * (max(1, len(body_lines)) + 0.55)
        if review:
            cxa = fig.add_axes([0.555, panel_bottom, 0.41, ph])
            cxa.set_axis_off(); cxa.set_xlim(0, 1); cxa.set_ylim(0, 1)
            cxa.add_patch(FancyBboxPatch((0.01, 0.015), 0.98, 0.97,
                          boxstyle="round,pad=0.010,rounding_size=0.02", fc="#FBF7F2",
                          ec="#C8A27A", lw=1.0, transform=cxa.transAxes, clip_on=False))
            cxa.text(0.05, 1.0 - 1.1 * line, "총평", fontsize=10.4, fontweight="bold",
                     va="top")
            y = 1.0 - 2.6 * line
            for k, (h, _key) in enumerate([("잘한 점", "good"), ("고칠 점", "fix"),
                                           ("다음에 해 볼 것", "next")]):
                cxa.text(0.05, y, h, fontsize=9.2, fontweight="bold", va="top",
                         color="#8B5E34")
                body_lines = review_wrapped[k] if k < len(review_wrapped) else []
                cxa.text(0.05, y - line * 1.05, "\n".join(body_lines), fontsize=8.6,
                         va="top", color="#333333", linespacing=1.5)
                y -= line * (len(body_lines) + 2.2)

    out = spec.get("out", "wongoji.png")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    unresolved = [n for n, _c, a in resolved if a is None]
    return {"out": out, "rows_used": len(lay["rows"]), "rows_drawn": nrows,
            "corrections": len(corrs), "unresolved": unresolved,
            "font": body, "wrap_rows": lay["wrap"], "hangs": list(lay["hangs"].keys())}


def export_layout(spec):
    """그림 대신 칸 좌표와 부호 앵커를 JSON으로 낸다(브라우저 SVG 렌더링용)."""
    ncols = spec.get("ncols", 20)
    blocks = build_blocks(spec)
    lay = layout(blocks, ncols)
    if spec.get("double_space"):
        lay = double_rows(lay)
    nrows = spec.get("nrows") or max(10, len(lay["rows"]) + 1)
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
