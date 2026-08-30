---
name: wongoji-qa
description: "원고지 첨삭기의 경계면을 검증한다. API 응답 vs app.js payload, export_layout 앵커 vs 예시 원고, 상태 전이 vs export 그리기, 입력 화면 fetch URL. 검증, QA, '이거 맞아?', 출시 전 점검, 모듈 끝난 뒤 확인, 회귀 요청 시 반드시 사용. 새 기능 설계만 할 때는 쓰지 않는다. 탐지 정확도 측정 자체는 wongoji-eval이 한다."
---

# 경계면 QA

존재 확인은 통과가 아니다. 생산자와 소비자를 **동시에 열어** 비교한다.

## 교차 비교 표

| 경계 | 왼쪽 | 오른쪽 |
|------|------|--------|
| 첨삭 응답 | `server.py` JSON keys | `web/app.js` `boot()` / `payloadOut` |
| 칸 좌표 | `export_layout` anchor | 예시 원고의 실제 오류 위치, SVG `data-n` |
| 상태 → 그림 | `c.state` | export가 draw / stet / skip |
| 들여쓰기 | 승인된 indent 항목 | `spec["indent"]` 0/1 |
| 라우팅 | FastAPI 마운트 경로 | fetch URL, `<a href>` |
| 점수 금지 | SPEC | UI 문자열, PDF caption, API 필드 |

## 모듈이 끝날 때마다

엔진 슬라이스 후: `pytest tests/test_layout.py tests/test_gate.py` (환경이 되면 전체).  
프론트 슬라이스 후: payload 키 목록을 grep으로 뽑아 계약과 대조.  
내보내기 슬라이스 후: 승인만 / 기각 포함 / 미검토만 세 경로.

## 리포트 형식

`_workspace/03_qa-inspector_report.md`

```
## 통과
- ...
## 실패
- [경계] 생산자 경로:줄 — 소비자 경로:줄 — 무엇을 고칠지
## 미검증
- 브라우저를 못 연 화면, kiwi 없는 규칙 계층 등
## 출시 게이트
- SPEC 표의 각 행 PASS/FAIL
```

실패를 구현자에게 보낼 때 패치 방향 한 줄을 붙인다. 다시 열지 말고 재검증 후 닫는다.

## 실행 assertion

- `spec_예시.json`의 6개 부호가 모두 `anchor`를 갖는다
- 데모 문장 `"재미있었다"`에 마침표가 없으면 punct 후보가 생긴다 (kiwi 있을 때)
- `payloadOut` 키가 ExportIn과 일치한다 (`text`, `corrections[]`, `review`, `format`, `audience`)
- 소스에 `score`/`점수`/`등급`이 학생 노출 경로에 없다

## 테스트 프롬프트

1. "입력 화면을 붙인 뒤 API랑 app.js 필드가 맞는지 봐줘"
2. "기각한 들여쓰기가 본문을 밀어내는지 레이아웃으로 확인해줘"
3. "출시 게이트 표  tol려서 PASS/FAIL 적어줘"
---


## 정확도 게이트 합류

이 스킬은 **배관**을 본다. API 응답과 화면이 같은 필드를 읽는가, 앵커가 칸에 앉는가.
배관이 다 통해도 틀린 곳을 못 찾으면 제품이 아니다. 그래서 출시 게이트 표에 정확도
게이트를 한 줄 더 넣는다.

```bash
python .claude/skills/wongoji-eval/scripts/validate_corpus.py tests/corpus
python .claude/skills/wongoji-eval/scripts/eval_accuracy.py
```

| 게이트 | 판정 기준 |
|--------|----------|
| 코퍼스 스키마 | `validate_corpus.py` 통과 |
| 유형별 퇴행 | 기준선 대비 F1 하락 0.01 초과 없음 |
| 음성 픽스처 | 위반 0건 |
| 지면 손실 | 기본 점수와 `--held` 점수 차이가 유형별 0.05 이내 |

**"실패 없음"을 쓰기 전에 무엇을 안 봤는지 쓴다.** 이전 리포트가 정확도를 아예 보지
않은 채 전 항목 PASS를 냈고, 사용자는 같은 시점에 "불완전하다"고 했다. 둘 다 사실
이었다. 검증 범위 밖은 **미검증**으로 명시하고 PASS에 섞지 않는다.

정확도 게이트 결과는 corpus-evaluator가 산출하고 당신이 출시 게이트 표에 합친다.
직접 측정하지 않는다.

## OCR 경계면 (2026-08-30 추가)

사진 입력이 들어오면서 검증할 이음새가 셋 늘었다.

| 경계면 | 확인 방법 |
|--------|----------|
| OCR 응답 ↔ 확인 화면 | `rows[].cells[]`를 화면이 칸 단위로 렌더하는가. 통짜 textarea로 되돌리면 칸 정보가 깨진다 |
| 확인 화면 ↔ 첨삭 파이프라인 | **교사가 확인 완료를 누르기 전에는 첨삭이 돌지 않는가.** 이 게이트를 우회하는 경로가 있으면 즉시 FAIL |
| 입력 격자 ↔ 출력 격자 | OCR `rows[].cells[]`와 `export_layout` 앵커가 같은 원문에서 같은 칸을 가리키는가 |

**빈 칸 보존을 반드시 확인한다.** OCR → 확인 화면 → 파이프라인을 지나며 `ch: ""`가
어디선가 `strip()`이나 `join()`으로 사라지면 문단 첫 칸 오류(O8)가 영영 안 잡힌다.
문단 첫 칸을 비운 원고와 안 비운 원고 두 장으로 끝까지 따라간다.

**이미지가 세션에 남는지 본다.** 학생 손글씨 사진은 개인정보다. 첨삭 완료 후
`data/sessions/`와 업로드 임시 디렉토리에 이미지가 남아 있으면 FAIL로 보고한다.
