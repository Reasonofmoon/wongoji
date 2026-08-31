# -*- coding: utf-8 -*-
"""원고지 첨삭의 색·글꼴·부호 이름. 한 곳에서만 정한다.

부호 종류(kind)와 한글 이름은 렌더러·SVG·게이트가 모두 참조하므로 여기가 단일 출처다.
"""
import os

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


def _bundled_dir():
    """글꼴이 담긴 디렉터리를 찾는다. **패키지를 import하지 않는다.**

    koreanize_matplotlib은 모듈 본문에서 distutils를 부르는데 파이썬 3.12에서 그것이
    빠졌다. 우리는 그 패키지의 동작이 아니라 담긴 .ttf 파일만 필요하므로, 본문을
    실행하지 않고 경로만 찾는다. 로컬에서는 setuptools의 distutils 대체물 덕에 import가
    통과해 이 함수가 없을 때도 돌았고, 서버에서만 조용히 실패했다.
    """
    global LAST_ERROR
    import importlib.util
    try:
        spec = importlib.util.find_spec("koreanize_matplotlib")
    except Exception as exc:
        LAST_ERROR = "find_spec 실패: %r" % (exc,)
        return None
    if spec is None:
        LAST_ERROR = "koreanize-matplotlib이 설치되지 않았다"
        return None
    roots = list(spec.submodule_search_locations or [])
    if not roots and spec.origin:
        roots = [os.path.dirname(spec.origin)]
    for root in roots:
        d = os.path.join(root, "fonts")
        if os.path.isdir(d):
            return d
    LAST_ERROR = "글꼴 디렉터리를 찾지 못했다: %s" % roots
    return None


def register_bundled():
    """묶어 온 한글 글꼴을 matplotlib에 등록한다. 반환: 등록된 이름들.

    서버에 한글 글꼴이 없으면 조용히 DejaVu로 떨어지고 글자가 전부 두부 상자로 나온다.
    실패해도 예외를 올리지 않는다 — 글꼴이 없다고 첨삭을 못 하게 만들 이유는 없다.
    """
    import os
    global LAST_ERROR
    try:
        import matplotlib.font_manager as fm
    except Exception as exc:
        LAST_ERROR = "matplotlib 없음: %r" % (exc,)
        return []
    d = _bundled_dir()
    if not d:
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
