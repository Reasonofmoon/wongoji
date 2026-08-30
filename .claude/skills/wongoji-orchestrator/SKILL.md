---
name: wongoji-orchestrator
description: "원고지 첨삭기를 출시 가능한 교사용 웹으로 올리는 에이전트 팀을 조율한다. 출시, 완성도, v1 구현, 시범 운영, 엔진/UI/QA 작업, 다시 실행, 재실행, 업데이트, 수정, 보완, 입력 화면만 다시, 게이트만 다시, 이전 결과 기반 개선 요청 시 반드시 이 스킬을 사용. 단순 코드 한 줄 질문은 직접 답한다."
---

# 원고지 첨삭기 출시 오케스트레이터

프로토타입을 한 학급 시범 운영이 가능한 교사용 웹으로 승격하는 통합 스킬.

## 실행 모드: 하이브리드

| Phase | 모드 | 이유 |
|-------|------|------|
| 0 컨텍스트 | 리더 단독 | 산출물 유무 분기 |
| 1 범위 잠금 | 서브 에이전트 | product-lead 1명 |
| 2 구현 | 에이전트 팀 | engine-dev ↔ frontend-dev 계약 조율 |
| 3 검증 | 서브 에이전트 | qa-inspector 격리 검증 |
| 4 수정 루프 | 에이전트 팀 | 실패 경계만 재구현 + 재검증 |

Claude Code에서는 `TeamCreate` / `SendMessage` / `TaskCreate`를 쓴다. Grok 세션에서는 `spawn_subagent`로 대응한다 (아래 런타임 표). 에이전트 정의 파일은 동일하다.

| 팀원 | 정의 파일 | Claude subagent_type | Grok subagent_type | 스킬 | 출력 |
|------|-----------|----------------------|--------------------|------|------|
| product-lead | `.claude/agents/product-lead.md` | product-lead 또는 Plan | plan | wongoji-product, wongoji-domain | `_workspace/01_product-lead_scope.md` |
| engine-dev | `.claude/agents/engine-dev.md` | engine-dev 또는 general-purpose | general-purpose | wongoji-engine, wongoji-domain | 코드 + `_workspace/02_engine-dev_notes.md` |
| frontend-dev | `.claude/agents/frontend-dev.md` | frontend-dev 또는 general-purpose | frontend-engineer | wongoji-frontend, wongoji-domain | `web/` + `_workspace/02_frontend-dev_notes.md` |
| qa-inspector | `.claude/agents/qa-inspector.md` | qa-inspector 또는 general-purpose | general-purpose | wongoji-qa, wongoji-domain | `_workspace/03_qa-inspector_report.md` |

Claude에서 Agent를 부를 때 `model: "opus"`를 명시한다. Grok에서는 부모 모델을 상속한다.

## 워크플로우

### Phase 0: 컨텍스트 확인

`_workspace/` 존재 여부를 본다.

- 없음 → 초기 실행. Phase 1
- 있음 + 부분 수정 ("입력 화면만", "게이트만") → 해당 에이전트만 재호출. 기존 파일을 읽고 덮어쓴다
- 있음 + 새 출시 목표 → `_workspace/`를 `_workspace_YYYYMMDD_HHMMSS/`로 옮긴 뒤 Phase 1

### Phase 1: 범위 잠금

**실행 모드:** 서브 에이전트

product-lead에게 `docs/기획서_원고지첨삭앱.md`와 `tasks/SPEC-v1-launch.md`를 읽히고 이번 실행 범위를 `_workspace/01_product-lead_scope.md`에 잠그게 한다. 2단계 기능이 들어오면 잘라 낸다.

### Phase 2: 구현

**실행 모드:** 에이전트 팀

```
TeamCreate(team_name: "wongoji-v1", members: [
  {name: "engine-dev", model: "opus", prompt: "에이전트 정의와 wongoji-engine 스킬을 읽고 파이프라인 단일화·게이트 결함·API 계약을 구현. 범위는 01_product-lead_scope.md."},
  {name: "frontend-dev", model: "opus", prompt: "에이전트 정의와 wongoji-frontend 스킬을 읽고 입력+검토 UI를 구현. API는 api-contract.md. 추측 필드 금지."}
])
TaskCreate([
  {title: "파이프라인 단일화와 게이트 결함", assignee: "engine-dev"},
  {title: "세션 디스크 저장과 API 계약", assignee: "engine-dev"},
  {title: "입력 화면과 검토 연결", assignee: "frontend-dev"},
  {title: "수정·내보내기 계약", assignee: "frontend-dev", depends_on: ["세션 디스크 저장과 API 계약"]}
])
```

통신: API shape이 바뀌면 engine-dev가 frontend-dev에게 즉시 알린다. 필드가 없으면 프론트가 만들지 않고 요청한다.

Grok 대안: 두 서브에이전트를 병렬로 띄우되, 프롬프트에 상대 산출물 경로와 "계약 파일 먼저 읽기"를 넣는다. 팀 통신이 없으면 리더가 계약 파일을 중간에 전달한다.

### Phase 3: 검증

**실행 모드:** 서브 에이전트

구현 팀을 정리한 뒤 qa-inspector를 격리 실행한다. 리포트의 실패가 있으면 Phase 4.

### Phase 4: 수정 루프

실패 경계의 생산자·소비자를 다시 팀에 넣어 고친다. 최대 2회. 그래도 남은 항목은 출시 게이트 FAIL로 사용자에게 보고하고 숨기지 않는다.

### Phase 5: 정리

`_workspace/`를 남긴다. 사용자에게 동작 방법, 통과한 게이트, 남은 FAIL을 보고한다.

## 데이터 흐름

```
사용자 요청
  → 01_product-lead_scope.md
  → engine-dev 코드 ↔ frontend-dev 코드  (api-contract.md)
  → 03_qa-inspector_report.md
  → 실패 시 부분 재구현
  → 출시 게이트 보고
```

중간 파일 이름: `{phase}_{agent}_{artifact}.md`

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 팀원 1명 실패 | 1회 재시작. 재실패 시 리더가 해당 슬라이스를 직접 하거나 재할당. 보고서에 누락 |
| kiwi/폰트 없는 환경 | 레이아웃·게이트 픽스처만 돌리고 규칙 계층 실측은 미검증 |
| API 계약 충돌 | 삭제하지 않고 양쪽 버전을 노트에 병기한 뒤 product-lead 기준으로 고친다 |
| 출시 게이트 과반 실패 | 사용자에게 알리고 출시 선언을 하지 않는다 |

## 테스트 시나리오

### 정상 흐름
1. "이 앱을 출시 가능하게 만들어줘"
2. Phase 1이 SPEC v1만 잠근다 (OCR 없음)
3. Phase 2에서 입력 화면 + 단일 파이프라인 상륙
4. Phase 3 레이아웃 픽스처 통과
5. README의 uvicorn 한 줄로 입력→검토→PNG가 된다

### 에러 흐름
1. frontend-dev가 `audience` 없이 export를 호출
2. qa가 계약 불일치를 양쪽에게 알림
3. 1회 수정 후 재검증
4. 리포트에 초기 실패와 재검증 통과를 남긴다

## 트리거 검증 (리더용)

Should-trigger: 출시, 시범 운영, 완성도, 입력 화면 붙여, 게이트만 다시, 이전 결과 개선, 엔진이랑 UI 같이 올려, 출시 전 QA, v1 범위 잠가줘, 다시 실행해서 기각 레이아웃 고쳐.

Should-NOT: 영어 에세이 첨삭 기획, 수능 문항 생성, 이 SVG를 포스터로만 다시 그려, kiwipiepy 설치 방법만, 커밋 메시지 추천, 일반 FastAPI 튜토리얼.
---
