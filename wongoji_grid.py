# -*- coding: utf-8 -*-
"""칸 격자의 좌표와 장 나눔.

칸 하나의 크기와 위치, 그리고 원고지 몇 장에 나눠 담을지를 정한다. 좌표를 쓰는 쪽은
여기 함수만 부른다 — 브라우저에서도 서버에서도 다시 계산하지 않는다.
"""
from wongoji_style import GRID

SHEET_ROWS = 20        # 한 장에 그리는 행. double_space면 실제 원고 10행 = 200자 원고지
FIG_W = 9.6
PAD_L, PAD_R = 1.15, 0.75   # 격자 좌우 여백(칸 단위). 왼쪽은 들여쓰기표 번호가 앉는다
PAD_T, PAD_B = 0.95, 0.25   # 위쪽은 부호가 행 밖으로 솟는 만큼

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
