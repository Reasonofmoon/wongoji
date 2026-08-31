# -*- coding: utf-8 -*-
"""교정부호 열넷의 작도.

부호 모양은 종이 첨삭의 관례를 따른다. 자리는 wongoji_grid가 준 좌표를 그대로 쓰고,
여기서는 모양만 그린다. 반환값은 번호표를 붙일 자리다.
"""
from wongoji_style import BOUNDARY_KINDS, RED
from wongoji_grid import gcy, gx, gy

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
