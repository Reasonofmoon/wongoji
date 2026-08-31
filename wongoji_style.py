# -*- coding: utf-8 -*-
"""원고지 첨삭의 색·글꼴·부호 이름. 한 곳에서만 정한다.

부호 종류(kind)와 한글 이름은 렌더러·SVG·게이트가 모두 참조하므로 여기가 단일 출처다.
"""

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


def pick_fonts():
    import matplotlib.font_manager as fm
    have = {f.name for f in fm.fontManager.ttflist}
    body = next((f for f in BODY_FONTS if f in have), "DejaVu Sans")
    ui = next((f for f in UI_FONTS if f in have), "DejaVu Sans")
    return body, ui
