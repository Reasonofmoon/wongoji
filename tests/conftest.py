# -*- coding: utf-8 -*-
"""테스트가 유료 API를 때리지 않게 하는 단일 관문.

pytest는 테스트 모듈을 수집하기 전에 conftest를 먼저 읽는다. **어느 파일 하나만
돌려도** 스위치가 서는 자리는 여기뿐이다.

예전에는 `test_ocr.py`와 `test_smoke.py`의 모듈 본문에서 각자 세웠다. 전체를 돌리면
수집 단계에서 그 모듈들이 임포트돼 우연히 스위치가 섰지만, 파일 하나만 돌리면 서지
않았다. 실측: `pytest tests/test_samples.py` 41.7초, CPU 6% — 94%가 네트워크 대기였다.
학년 10개를 종단으로 도는 테스트가 전부 실호출로 나가고 있었다.

CLAUDE.md는 "테스트는 전체가 아닌 관련 파일 단위로 실행"을 규칙으로 둔다. 문서화된
작업 방식이 정확히 그 경로를 밟았다.
"""
import os
import sys

os.environ.setdefault("CHUMSAK_NO_LLM", "1")

# 테스트가 저장소 뿌리의 모듈을 임포트한다. 각 파일이 따로 sys.path를 만지지 않게 한다.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
