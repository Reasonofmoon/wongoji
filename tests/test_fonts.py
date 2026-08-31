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


def test_bundled_font_found_without_importing_the_package():
    """패키지를 import하면 서버에서 죽는다. 경로만 찾아야 한다.

    koreanize_matplotlib은 모듈 본문에서 distutils를 부르는데 파이썬 3.12에 그것이
    없다. 로컬은 setuptools의 대체물 덕에 통과하고 **서버에서만** 조용히 실패해
    산출물의 한글이 전부 두부 상자가 됐다. 그 조건을 그대로 재현한다.
    """
    import subprocess
    code = (
        "import sys; sys.modules['distutils'] = None\n"
        "sys.path.insert(0, %r)\n"
        "import wongoji_style as S\n"
        "names = S.register_bundled()\n"
        "assert names, 'distutils 없이 글꼴 등록 실패: %%s' %% S.LAST_ERROR\n"
        "assert 'koreanize_matplotlib' not in sys.modules, '패키지를 import했다'\n"
        "print('ok')\n" % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


def test_health_exposes_font_report():
    """조용한 실패를 밖에서 볼 수 있어야 한다. 이 결함을 찾는 데 이것이 필요했다."""
    import wongoji_style as S
    rep = S.font_report()
    for key in ("body", "ui", "bundled", "hangul_ok", "error"):
        assert key in rep
    assert rep["hangul_ok"] is True, rep
