# -*- coding: utf-8 -*-
"""원고지 + 교정부호를 SVG로 낸다.

칸 좌표·부호 앵커 계산은 wongoji_render의 검증된 함수를 그대로 쓴다.
브라우저는 이 SVG를 받아 상호작용(선택·승인·기각·필터)만 담당한다.
부호는 <g class="mk" data-n="3"> 로 묶여 있어 CSS/JS로 개별 제어할 수 있다.
"""
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wongoji_render import (BOUNDARY_KINDS, KIND_LABEL, build_blocks, double_rows,
                            layout, locate_boundary, locate_span, resolve)

CW = 34.0            # 칸 너비(px)
CH = 34.0            # 칸 높이
GAP = 0.16           # 10칸 뒤 홈 간격(칸 너비 비율)
PAD = 26.0           # 격자 바깥 여백
RED = "#C0392B"
GRID = "#9A9A9A"
FRAME = "#333333"


def gx(c, ncols):
    g = GAP * CW if (ncols > 10 and c >= 10) else 0.0
    return PAD + c * CW + g


def gy(r):
    return PAD + r * CH


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- 부호 작도
def _arc(x0, x1, y, h, down=False):
    """양 끝을 붙인 호(붙임표용)."""
    k = -h if not down else h
    return "M %.1f %.1f Q %.1f %.1f %.1f %.1f" % (x0, y, (x0 + x1) / 2, y + k, x1, y)


def _hook(x, y, d=1.0, w=6.0):
    """갈고리(화살촉 대용)."""
    return "M %.1f %.1f L %.1f %.1f L %.1f %.1f" % (x - w, y - d * w, x, y, x - w, y + d * w)


def mark_paths(kind, a, ncols, text=None):
    """부호 하나를 그리는 (paths, texts) 반환. a는 export_layout의 anchor."""
    P, T = [], []
    if a["type"] == "boundary":
        x, r = gx(a["c"], ncols), a["r"]
        ytop, ybot = gy(r), gy(r + 1)
        ymid = (ytop + ybot) / 2
        if kind == "space":
            P.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f"
                     % (x - 9, ytop - 13, x, ytop + 2, x + 9, ytop - 13))
        elif kind in ("insert", "punct"):
            P.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f"
                     % (x - 9, ytop - 13, x, ytop + 2, x + 9, ytop - 13))
            if text:
                T.append((x, ytop - 17, text, 13 if kind == "punct" else 15))
        elif kind == "newline":
            P.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f"
                     % (x, ytop + 2, x, ybot + CH * 0.42, x - CW * 0.42, ybot + CH * 0.42))
            P.append(_hook(x - CW * 0.42 + 7, ybot + CH * 0.42, 1.0, 6.0))
        elif kind == "joinline":
            P.append("M %.1f %.1f C %.1f %.1f %.1f %.1f %.1f %.1f"
                     % (x, ymid, x + 22, ymid + 10, x - 26, ybot + 6, x - 6, ybot + CH * 0.5))
            P.append(_hook(x - 6, ybot + CH * 0.5, -1.0, 6.0))
    else:
        r, c0, c1 = a["r"], a["c0"], a["c1"]
        x0, x1 = gx(c0, ncols), gx(c1, ncols) + CW
        ytop, ybot = gy(r), gy(r + 1)
        ymid = (ytop + ybot) / 2
        if kind == "join":
            gc = a.get("gap")
            gc = gc if gc is not None else (c0 + c1) // 2
            a0, a1 = gx(gc, ncols) - 5, gx(gc, ncols) + CW + 5
            P.append(_arc(a0, a1, ymid, 11))
            P.append(_arc(a0, a1, ymid, 11, down=True))
        elif kind == "delete":
            P.append("M %.1f %.1f L %.1f %.1f" % (x0, ymid - 4, x1, ymid - 4))
            P.append("M %.1f %.1f L %.1f %.1f" % (x0, ymid + 4, x1, ymid + 4))
            P.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f"
                     % (x1, ymid + 4, x1 + 5, ymid + 4, x1 + 5, ytop - 8))
            P.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f"
                     % (x1 + 1, ytop - 3, x1 + 5, ytop - 8, x1 + 9, ytop - 3))
        elif kind == "replace":
            P.append("M %.1f %.1f L %.1f %.1f" % (x0, ymid, x1, ymid))
            P.append("M %.1f %.1f L %.1f %.1f" % (x1, ymid, x1, ytop - 6))
            if text:
                T.append(((x0 + x1) / 2, ytop - 10, text, 15))
        elif kind == "swap":
            xm = gx((c0 + c1 + 1) // 2, ncols)
            P.append("M %.1f %.1f C %.1f %.1f %.1f %.1f %.1f %.1f"
                     % (x0, ytop - 4, x0, ytop - 20, xm, ytop - 20, xm, ytop - 4))
            P.append("M %.1f %.1f C %.1f %.1f %.1f %.1f %.1f %.1f"
                     % (xm, ybot + 4, xm, ybot + 20, x1, ybot + 20, x1, ybot + 4))
        elif kind in ("indent", "outdent"):
            d = 1.0 if kind == "indent" else -1.0
            w = CW * 0.5
            bx = x0 - 16 if kind == "indent" else x0 + 16
            P.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f L %.1f %.1f"
                     % (bx, ytop + 6, bx + d * w, ytop + 6, bx + d * w, ybot - 6,
                        bx, ybot - 6))
        elif kind in ("up", "down"):
            d = -1.0 if kind == "up" else 1.0
            y = ytop + 4 if kind == "up" else ybot - 4
            P.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f"
                     % (x1 + 4, y, x1 + 4, y + d * 20, x1 + 4 + 18, y + d * 20))
            P.append(_hook(x1 + 22, y + d * 20, 1.0, 6.0))
        elif kind == "stet":
            P.append("M %.1f %.1f L %.1f %.1f" % (x0, ybot - 3, x1, ybot - 3))
            T.append(((x0 + x1) / 2, ybot + 13, "살림", 11))
    return P, T


# ---------------------------------------------------------------- SVG 조립
def to_svg(data, body_font="'Nanum Myeongjo','AppleMyungjo','Batang',serif",
           ui_font="'Nanum Gothic','Apple SD Gothic Neo','Malgun Gothic',sans-serif"):
    g = data["grid"]
    ncols, nrows = g["ncols"], g["nrows"]
    W = gx(ncols - 1, ncols) + CW + PAD
    H = gy(nrows) + PAD
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.0f %.0f" '
           'class="wongoji" role="img">' % (W, H)]
    out.append('<rect x="0" y="0" width="%.0f" height="%.0f" fill="white"/>' % (W, H))

    # 격자
    out.append('<g class="grid" stroke="%s" stroke-width="0.8" fill="none">' % GRID)
    for r in range(nrows + 1):
        out.append('<path d="M %.1f %.1f L %.1f %.1f"/>'
                   % (gx(0, ncols), gy(r), gx(ncols - 1, ncols) + CW, gy(r)))
    for c in range(ncols + 1):
        x = gx(c, ncols) if c < ncols else gx(ncols - 1, ncols) + CW
        out.append('<path d="M %.1f %.1f L %.1f %.1f"/>' % (x, gy(0), x, gy(nrows)))
    out.append('</g>')
    out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" '
               'stroke="%s" stroke-width="1.6"/>'
               % (gx(0, ncols), gy(0), gx(ncols - 1, ncols) + CW - gx(0, ncols),
                  nrows * CH, FRAME))

    # 본문
    out.append('<g class="body" font-family="%s" font-size="20" fill="#111" '
               'text-anchor="middle">' % body_font)
    for cell in data["cells"]:
        fs = 20 if len(cell["tok"]) == 1 else 13
        out.append('<text x="%.1f" y="%.1f" font-size="%d">%s</text>'
                   % (gx(cell["c"], ncols) + CW / 2, gy(cell["r"]) + CH * 0.72, fs,
                      esc(cell["tok"])))
    for r, hp in data.get("hangs", {}).items():
        out.append('<text x="%.1f" y="%.1f" text-anchor="start">%s</text>'
                   % (gx(ncols - 1, ncols) + CW + 3, gy(int(r)) + CH * 0.72, esc(hp)))
    out.append('</g>')

    # 부호
    out.append('<g class="marks" font-family="%s">' % body_font)
    for c in data["corrections"]:
        if not c.get("anchor"):
            continue
        paths, texts = mark_paths(c["kind"], c["anchor"], ncols, c.get("text"))
        out.append('<g class="mk mk-%s" data-n="%d" data-kind="%s" data-state="%s">'
                   % (esc(c["kind"]), c["n"], esc(c["kind"]), esc(c.get("state", "pending"))))
        for p in paths:
            out.append('<path d="%s" fill="none" stroke="%s" stroke-width="2" '
                       'stroke-linecap="round"/>' % (p, RED))
        for tx, ty, tt, fs in texts:
            out.append('<text x="%.1f" y="%.1f" font-size="%d" fill="%s" '
                       'text-anchor="middle">%s</text>' % (tx, ty, fs, RED, esc(tt)))
        # 번호 표찰
        a = c["anchor"]
        lx = gx(a["c"] if a["type"] == "boundary" else a["c1"], ncols) + CW * 0.9
        ly = gy(a["r"]) - 6
        out.append('<g class="tag"><circle cx="%.1f" cy="%.1f" r="9" fill="white" '
                   'stroke="%s" stroke-width="1.2"/><text x="%.1f" y="%.1f" '
                   'font-family="%s" font-size="10" fill="%s" text-anchor="middle" '
                   'font-weight="bold">%d</text></g>'
                   % (lx, ly, RED, lx, ly + 3.6, ui_font, RED, c["n"]))
        out.append('</g>')
    out.append('</g></svg>')
    return "\n".join(out)


def build(spec):
    """spec -> {svg, data}. spec은 wongoji_render와 같은 형식."""
    from wongoji_render import export_layout
    data = export_layout(spec)
    return {"svg": to_svg(data), "data": data}


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    res = build(spec)
    out = spec.get("out", "wongoji.svg")
    open(out, "w", encoding="utf-8").write(res["svg"])
    print(json.dumps({"out": out, "cells": len(res["data"]["cells"]),
                      "marks": sum(1 for c in res["data"]["corrections"] if c["anchor"]),
                      "unresolved": [c["n"] for c in res["data"]["corrections"]
                                     if not c["anchor"]]}, ensure_ascii=False))
