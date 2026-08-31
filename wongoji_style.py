# -*- coding: utf-8 -*-
"""원고지 첨삭의 색·글꼴·부호 이름. 한 곳에서만 정한다.

부호 종류(kind)와 한글 이름은 렌더러·SVG·게이트가 모두 참조하므로 여기가 단일 출처다.
"""

# 서버(리눅스)에는 한글 글꼴이 없다. DejaVu로 떨어지면 모든 한글이 두부 상자로 나온다.
# koreanize-matplotlib(MIT)이 나눔고딕을 담아 배포하므로 그것을 등록해 쓴다.
BUNDLED = "NanumGothic"
LAST_ERROR = None    # 글꼴 등록이 왜 실패했는지 남긴다
BODY_FONTS = [BUNDLED, "AppleMyungjo", "NanumMyeongjo", "Apple SD Gothic Neo",
              "Malgun Gothic", "Noto Sans CJK KR", "DejaVu Sans"]
UI_FONTS = [BUNDLED, "Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic",
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


def register_bundled():
    """묶어 온 한글 글꼴을 matplotlib에 등록한다. 반환: 등록된 이름들.

    서버에 한글 글꼴이 없으면 조용히 DejaVu로 떨어지고 글자가 전부 두부 상자로 나온다.
    실패해도 예외를 올리지 않는다 — 글꼴이 없다고 첨삭을 못 하게 만들 이유는 없다.
    """
    import os
    global LAST_ERROR
    try:
        import koreanize_matplotlib as km
        import matplotlib.font_manager as fm
    except Exception as exc:
        LAST_ERROR = "import 실패: %r" % (exc,)
        return []
    d = os.path.join(os.path.dirname(km.__file__), "fonts")
    if not os.path.isdir(d):
        LAST_ERROR = "글꼴 디렉터리가 없다: %s" % d
        return []
    names = []
    for name in sorted(os.listdir(d)):
        if not name.lower().endswith((".ttf", ".otf")):
            continue
        path = os.path.join(d, name)
        try:
            fm.fontManager.addfont(path)
            names.append(fm.FontProperties(fname=path).get_name())
        except Exception as exc:
            LAST_ERROR = "%s 등록 실패: %r" % (name, exc)
            continue
    if not names:
        LAST_ERROR = "등록된 글꼴이 없다: %s" % d
    return names


def font_report():
    """왜 한글이 깨지는지 밖에서 볼 수 있게 한다. 조용히 실패하면 원인을 못 찾는다."""
    bundled = register_bundled()
    body, ui = pick_fonts()
    ok = None
    try:
        from matplotlib import font_manager as fm
        from fontTools.ttLib import TTFont, TTCollection
        path = fm.findfont(fm.FontProperties(family=body), fallback_to_default=False)
        cmap = (TTCollection(path, lazy=True).fonts[0] if path.lower().endswith(".ttc")
                else TTFont(path, lazy=True)).getBestCmap()
        ok = ord("가") in cmap
    except Exception as exc:
        ok = "확인 실패: %r" % (exc,)
        path = None
    return {"body": body, "ui": ui, "bundled": sorted(set(bundled)),
            "path": path, "hangul_ok": ok, "error": LAST_ERROR}


def pick_fonts():
    """본문·UI 글꼴을 고른다. 어디서 돌든 같은 글꼴이 나오게 묶어 온 것을 먼저 본다."""
    import matplotlib.font_manager as fm
    register_bundled()
    have = {f.name for f in fm.fontManager.ttflist}
    body = next((f for f in BODY_FONTS if f in have), "DejaVu Sans")
    ui = next((f for f in UI_FONTS if f in have), "DejaVu Sans")
    return body, ui
