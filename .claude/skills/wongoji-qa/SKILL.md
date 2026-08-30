---
name: wongoji-qa
description: "원고지 첨삭기의 경계면을 검증한다. API 응답 vs app.js payload, export_layout 앵커 vs 예시 원고, 상태 전이 vs export 그리기, 입력 화면 fetch URL. 검증, QA, '이거 맞아?', 출시 전 점검, 모듈 끝난 뒤 확인, 회귀 요청 시 반드시 사용. 새 기능 설계만 할 때는 쓰지 않는다."
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
