#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""원고지 첨삭본을 그린다. 조립만 하고, 계산은 이웃 모듈이 한다.

    python wongoji_render.py spec.json

| 모듈 | 맡은 일 |
|------|---------|
| `wongoji_style` | 색·글꼴·부호 이름 |
| `wongoji_text`  | 원문 -> 칸 배치 (그림 없음) |
| `wongoji_grid`  | 칸 좌표와 장 나눔 |
| `wongoji_marks` | 교정부호 작도 |
| `wongoji_panel` | 범례와 총평 |

**`export_layout()`이 칸 좌표의 단일 출처 API다.** 브라우저 SVG도 서버 PNG도 이 함수가
낸 좌표만 쓴다. 내부가 여러 모듈로 나뉘었을 뿐 그 계약은 그대로다.

아래 재수출은 호환을 위한 것이다. 새 코드는 각 모듈에서 직접 가져다 쓴다.
"""
import json
import sys

from wongoji_style import (BLUE, BODY_FONTS, BOUNDARY_KINDS, GRID, HANG,  # noqa: F401
                           KIND_LABEL, RED, SPAN_KINDS, UI_FONTS, pick_fonts)
from wongoji_text import (build_blocks, clip_lines, double_rows, layout,  # noqa: F401
                          locate_boundary, locate_span, resolve, tokenize)
from wongoji_grid import (FIG_W, PAD_B, PAD_L, PAD_R, PAD_T, SHEET_ROWS,  # noqa: F401
                          draw_grid, fill_grid, gcx, gcy, geom, gx, gy, paginate,
                          sheet_inches, slice_lay)
from wongoji_marks import draw_mark
from wongoji_panel import PANEL_LINE, draw_panel, panel_height, wrap_panel

__all__ = ["render", "export_layout", "main", "BOUNDARY_KINDS", "SPAN_KINDS",
           "KIND_LABEL", "RED", "GRID", "SHEET_ROWS", "PANEL_LINE", "layout",
           "build_blocks", "double_rows", "paginate", "panel_height", "geom"]


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
