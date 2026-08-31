# -*- coding: utf-8 -*-
"""교정 내용 범례와 총평.

축 안의 y를 **인치**로 둔다. 줄 높이를 그림 인치로 재 놓고 축 비율 좌표에 쓰면
지면이 길어질수록 글자가 겹친다. 실제로 그렇게 겹쳤다.
"""
from wongoji_style import KIND_LABEL, RED
from wongoji_text import clip_lines

PANEL_LINE = 0.17      # 범례·총평의 한 줄 높이(인치)

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
