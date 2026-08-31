# -*- coding: utf-8 -*-
"""고른 글꼴이 한글을 실제로 담고 있는지 본다.

서버(리눅스)에 한글 글꼴이 없으면 matplotlib이 조용히 DejaVu로 떨어진다. 예외가 나지
않아 배포는 성공하고, 산출물의 한글만 전부 두부 상자가 된다. 이름만 확인해서는 못 잡고
글리프 표를 봐야 잡힌다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE = "가원고지첨삭힣"


def _font_path(name):
    from matplotlib import font_manager as fm
    return fm.findfont(fm.FontProperties(family=name), fallback_to_default=False)


def _cmap(path):
    from fontTools.ttLib import TTFont, TTCollection
    if path.lower().endswith(".ttc"):
        return TTCollection(path, lazy=True).fonts[0].getBestCmap()
    return TTFont(path, lazy=True).getBestCmap()


def test_bundled_font_is_available():
    """묶어 온 글꼴이 없으면 서버에서 한글이 깨진다."""
    import wongoji_style as S
    assert S.register_bundled(), "koreanize-matplotlib의 글꼴을 등록하지 못했다"


def test_picked_fonts_cover_hangul():
    import wongoji_style as S
    body, ui = S.pick_fonts()
    for label, name in (("본문", body), ("UI", ui)):
        cmap = _cmap(_font_path(name))
        missing = [c for c in SAMPLE if ord(c) not in cmap]
        assert not missing, "%s 글꼴 '%s'에 없는 글자: %s" % (label, name, missing)


def test_body_font_is_deterministic():
    """로컬과 서버가 다른 글꼴로 그리면 같은 원고가 달라 보인다."""
    import wongoji_style as S
    assert S.pick_fonts()[0] == S.BUNDLED
