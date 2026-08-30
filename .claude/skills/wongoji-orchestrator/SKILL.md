---
name: wongoji-orchestrator
description: "원고지 첨삭기를 출시 가능한 교사용 웹으로 올리고, 첨삭 정확도를 끌어올리고, 사진 입력(OCR)을 붙이는 에이전트 팀을 조율한다. 출시, 완성도, v1 구현, 시범 운영, 엔진/UI/QA 작업, 그리고 맞춤법을 못 잡는다, 오류를 다 못 찾는다, 오탐이 난다, 정확도 개선, 재현율, 규칙 추가, 코퍼스, 평가, 불완전하다, 보완해달라는 요청 시 반드시 이 스킬을 사용. 다시 실행, 재실행, 업데이트, 수정, 보완, 입력 화면만 다시, 게이트만 다시, 맞춤법만 다시, OCR만 다시, 이전 결과 기반 개선도 포함. 사진으로 올린다, 손글씨 인식, 스캔, 이미지 업로드, 타이핑 없이 입력 요청도 이 스킬이다. 단순 코드 한 줄 질문은 직접 답한다."
---

# 원고지 첨삭기 오케스트레이터

두 개의 레인이 있다. 요청이 어느 레인인지부터 가린다.

| 레인 | 언제 | 묻는 것 |
|------|------|--------|
| **A. 출시 레인** | 화면·API·내보내기·배포·범위 | 교사가 이 앱을 **쓸 수 있는가** |
| **B. 정확도 레인** | 맞춤법·오탐·재현율·규칙·코퍼스 | 교사가 이 앱을 **믿을 수 있는가** |
| **C. 입력 레인** | 사진 업로드·손글씨 인식·확인 화면 | 교사가 이 앱을 **시작할 수 있는가** |

배관이 다 통해도 틀린 곳을 못 찾으면 제품이 아니고, 다 찾아도 입력이 힘들면 아무도
쓰지 않는다. 세 레인은 독립적으로 돌지만 출시 게이트에서 합쳐진다.

**레인 판별:** "안 열린다·화면이 없다·내보내기·배포" → A. "못 잡는다·틀린 걸 놓친다·
없는 걸 표시한다·정확도·규칙·코퍼스" → B. "사진·스캔·손글씨·타이핑 없이·OCR" → C.

**순서:** C → B → A. 입력이 바뀌면 첨삭에 들어가는 텍스트가 바뀌고, 정확도가 바뀌면
지면 밀도가 바뀌고, 밀도가 바뀌면 화면이 흔들린다. 거꾸로 가면 두 번 고친다.

**C와 B가 함께 걸리면 C부터 확인한다.** "맞춤법을 못 잡는다"의 원인이 규칙이 아니라
OCR의 자동 교정일 수 있다. 사진으로 넣은 원고라면 **교정 침묵률을 먼저 재고**, 그
다음에 규칙을 의심한다. 순서를 뒤집으면 멀쩡한 규칙을 헛되이 고친다.

## 팀 구성

| 팀원 | 정의 파일 | 레인 | Claude subagent_type | 스킬 | 출력 |
|------|-----------|------|----------------------|------|------|
| product-lead | `.claude/agents/product-lead.md` | A·B | product-lead 또는 Plan | wongoji-product, wongoji-domain | `_workspace/01_product-lead_scope.md` |
| engine-dev | `.claude/agents/engine-dev.md` | A·B | engine-dev 또는 general-purpose | wongoji-engine, wongoji-domain | 코드 + `_workspace/02_engine-dev_notes.md` |
| frontend-dev | `.claude/agents/frontend-dev.md` | A | frontend-dev 또는 general-purpose | wongoji-frontend, wongoji-domain | `web/` + `_workspace/02_frontend-dev_notes.md` |
| qa-inspector | `.claude/agents/qa-inspector.md` | A·B | qa-inspector 또는 general-purpose | wongoji-qa, wongoji-domain | `_workspace/03_qa-inspector_report.md` |
| **orthography-lead** | `.claude/agents/orthography-lead.md` | B | orthography-lead 또는 general-purpose | wongoji-orthography, wongoji-domain | `rule_*` 코드 + `_workspace/04_orthography_rules.md` |
| **corpus-evaluator** | `.claude/agents/corpus-evaluator.md` | B·C | corpus-evaluator 또는 general-purpose | wongoji-eval | `tests/corpus/` + `_workspace/05_evaluator_report.md` |
| **ocr-dev** | `.claude/agents/ocr-dev.md` | C | ocr-dev 또는 general-purpose | wongoji-ocr, wongoji-domain | 입력 경로 + `_workspace/06_ocr-dev_notes.md` |

Claude에서 Agent를 부를 때 `model: "opus"`를 명시한다. Grok 세션에서는
`spawn_subagent`로 대응하고 부모 모델을 상속한다. 에이전트 정의 파일은 동일하다.

## 실행 모드: 하이브리드

| Phase | 레인 | 모드 | 이유 |
|-------|------|------|------|
| 0 컨텍스트 | 공통 | 리더 단독 | 레인 판별과 산출물 유무 분기 |
| 1 범위 잠금 | A·B | 서브 에이전트 | product-lead 1명 |
| 2 구현 | A | 에이전트 팀 | engine-dev ↔ frontend-dev 계약 조율 |
| 3 검증 | A | 서브 에이전트 | qa-inspector 격리 검증 |
| 4 수정 루프 | A | 에이전트 팀 | 실패 경계만 재구현 + 재검증 |
| **E1 코퍼스** | B | 서브 에이전트 | corpus-evaluator 단독. 채점표를 먼저 만든다 |
| **E2 기준선** | B | 서브 에이전트 | 측정만. 여기서 규칙을 고치지 않는다 |
| **E3 규칙 루프** | B | 에이전트 팀 | orthography-lead ↔ corpus-evaluator 생성-검증 |
| **E4 지면 반영** | B | 에이전트 팀 | engine-dev ↔ frontend-dev, 전수 표시로 늘어난 밀도 |
| **I1 인식 계약** | C | 서브 에이전트 | ocr-dev 단독. 칸 스키마와 프롬프트를 먼저 못 박는다 |
| **I2 확인 화면** | C | 에이전트 팀 | ocr-dev ↔ frontend-dev. 칸 단위 편집 게이트 |
| **I3 침묵 검증** | C | 에이전트 팀 | ocr-dev ↔ corpus-evaluator. 교정 침묵률·CER·칸 정렬 |

## Phase 0: 컨텍스트 확인

`_workspace/`와 `tests/corpus/` 존재 여부를 본다.

- 둘 다 없음 → 초기 실행. 레인 판별 후 Phase 1
- 있음 + 부분 수정 ("입력 화면만", "게이트만", "조사 규칙만") → 해당 에이전트만
  재호출. 기존 파일을 읽고 덮어쓴다
- 있음 + 새 출시 목표 → `_workspace/`를 `_workspace_YYYYMMDD_HHMMSS/`로 옮긴다.
  **`tests/corpus/`는 옮기지 않는다.** 코퍼스와 기준선은 누적 자산이다

## 레인 A: 출시

### Phase 1: 범위 잠금
**모드:** 서브 에이전트. product-lead에게 `docs/기획서_원고지첨삭앱.md`와
`tasks/SPEC-v1-launch.md`를 읽히고 이번 범위를 `_workspace/01_product-lead_scope.md`에
잠그게 한다. 2단계 기능(회차·학급·자동 채점)이 들어오면 잘라 낸다.

**OCR은 더 이상 2단계가 아니다** (2026-08-30 반전). 다만 조건부다 — 교사 확인 화면,
자동 교정 금지, 텍스트 입력 경로 유지, 이미지 미보관. 조건 없이 OCR만 들어오면 막는다.

### Phase 2: 구현
**모드:** 에이전트 팀

```
TeamCreate(team_name: "wongoji-v1", members: [
  {name: "engine-dev", model: "opus", prompt: "에이전트 정의와 wongoji-engine 스킬을 읽고 파이프라인·게이트·API 계약을 구현. 범위는 01_product-lead_scope.md."},
  {name: "frontend-dev", model: "opus", prompt: "에이전트 정의와 wongoji-frontend 스킬을 읽고 입력+검토 UI를 구현. API는 api-contract.md. 추측 필드 금지."}
])
```

통신: API shape이 바뀌면 engine-dev가 frontend-dev에게 즉시 알린다. 필드가 없으면
프론트가 만들지 않고 요청한다.

### Phase 3: 검증
**모드:** 서브 에이전트. 구현 팀을 정리한 뒤 qa-inspector를 격리 실행한다.

### Phase 4: 수정 루프
실패 경계의 생산자·소비자를 다시 팀에 넣어 고친다. 최대 2회. 남은 항목은 출시 게이트
FAIL로 보고하고 숨기지 않는다.

## 레인 B: 정확도

이 레인의 원칙 하나: **측정이 구현보다 먼저다.** 기준선 없이 규칙을 고치면 개선인지
퇴행인지 모른다. E1·E2를 건너뛰고 E3으로 가지 않는다.

### Phase E1: 코퍼스 구축
**모드:** 서브 에이전트 (corpus-evaluator)

```
Agent(subagent_type: "corpus-evaluator", model: "opus", prompt:
  "wongoji-eval 스킬과 references/corpus-schema.md를 읽고, 오류 태그가 붙은 합성 골드
   코퍼스를 tests/corpus/에 만든다. 분포 목표(학년·갈래·길이·유형)를 지키고 negatives를
   같은 편에 넣는다. validate_corpus.py를 통과시킨 뒤 끝낸다.")
```

기존 코퍼스가 있으면 **덮지 말고 늘린다.** 유형별 표본이 5편 미만인 유형부터 채운다.

### Phase E2: 기준선 측정
**모드:** 서브 에이전트 (corpus-evaluator)

`eval_accuracy.py`를 규칙 계층만으로 돌려 유형별 F1을 `_baseline.json`에 남기고,
`_workspace/05_evaluator_report.md`에 유형별 표와 놓친 오류 목록을 쓴다.

**여기서 규칙을 고치지 않는다.** 측정자와 구현자를 분리하는 이유가 이 Phase에 있다.
기준선을 만든 사람이 곧바로 그 점수를 올리면 채점표를 자기에게 유리하게 만든다.

### Phase E3: 규칙 루프
**모드:** 에이전트 팀 (생성-검증 패턴)

```
TeamCreate(team_name: "wongoji-accuracy", members: [
  {name: "orthography-lead", model: "opus", prompt: "wongoji-orthography 스킬과 오류유형_카탈로그를 읽고, 05_evaluator_report.md에서 재현율이 가장 낮은 유형부터 rule_*()로 구현한다. 오탐 억제 조건과 type·confidence를 함께 심는다. 한 번에 한 유형."},
  {name: "corpus-evaluator", model: "opus", prompt: "wongoji-eval 스킬을 읽고, 규칙이 하나 올라올 때마다 재측정해 목표 유형 상승과 다른 유형 유지를 확인한다. 음성 픽스처 위반은 즉시 FAIL로 되돌린다."}
])
TaskCreate([
  {title: "재현율 최저 유형 규칙 구현", assignee: "orthography-lead"},
  {title: "구현 유형 재측정과 회귀 판정", assignee: "corpus-evaluator", depends_on: ["재현율 최저 유형 규칙 구현"]},
  {title: "오탐 억제 조건 보강", assignee: "orthography-lead", depends_on: ["구현 유형 재측정과 회귀 판정"]},
  {title: "기준선 갱신", assignee: "corpus-evaluator", depends_on: ["오탐 억제 조건 보강"]}
])
```

루프 종료 조건 — 아래 중 하나:
- 목표 유형 전부가 기준선 대비 상승하고 퇴행·음성 위반이 없다
- 한 유형에서 3회 연속 개선 실패 → 그 유형을 `uncertain`으로 낮추고 다음 유형으로
- 사용자가 정한 반복 상한(기본 유형 5개) 도달

**개선 실패를 반복하지 않는다.** 같은 유형에서 두 번 퇴행하면 규칙을 더 깎지 말고
`held`로 보낸 뒤 다음 유형으로 넘어간다. 세 번째 시도는 거의 항상 오탐을 낳는다.

### Phase E4: 지면 반영
**모드:** 에이전트 팀 (engine-dev + frontend-dev)

표기 전수 표시로 항목 수가 늘면 지면이 터진다. 이 Phase가 그것을 받는다.

- engine-dev: `focus_filter`를 층위별로 나눈다. 표기는 상한 없이, 내용만 상한.
  지면이 모자라면 항목을 버리지 말고 `nrows`를 늘리거나 장을 나눈다
- frontend-dev: 늘어난 부호가 서로 겹쳐 읽히지 않는지, 검토 목록이 스크롤되는지 본다
- corpus-evaluator: `--held` 점수와 기본 점수 차이가 줄었는지 확인한다. 차이가 남아
  있으면 아직 잘리고 있는 것이다

## 레인 C: 입력 (OCR)

이 레인의 원칙 하나: **OCR이 맞춤법을 고치면 첨삭기는 죽는다.** 학생이 쓴 `학교은`을
`학교는`으로 고쳐 넘기면 첨삭할 오류가 사라진다. 증상은 "맞춤법을 못 잡는다"인데
원인은 규칙이 아니라 입구다. 규칙을 아무리 고쳐도 점수가 오르지 않는다.

### Phase I1: 인식 계약
**모드:** 서브 에이전트 (ocr-dev)

칸 격자 응답 스키마(`{row, col, ch, conf}`)와 프롬프트 규약을 먼저 못 박는다.
**빈 칸을 `ch: ""`로 남기는 것**이 계약의 핵심이다. 글자만 이어 붙이면 문단 첫 칸
정보가 사라지고 O8 오류를 영원히 못 잡는다.

참조 구현(`github.com/kukbapman/ocr`)은 호출 형태만 본다. LICENSE가 없어 코드를
복사하지 않고, "IGNORE ALL HANDWRITING" 규칙은 **정반대로 뒤집는다**.

### Phase I2: 확인 화면
**모드:** 에이전트 팀 (ocr-dev + frontend-dev)

```
TeamCreate(team_name: "wongoji-input", members: [
  {name: "ocr-dev", model: "opus", prompt: "wongoji-ocr 스킬과 references/vision-ocr-계약.md를 읽고 업로드→OCR→칸 격자 응답까지의 FastAPI 경로를 구현. 자동 교정 차단과 conf를 반드시 넣는다."},
  {name: "frontend-dev", model: "opus", prompt: "wongoji-frontend와 wongoji-ocr을 읽고 교사 확인 화면을 구현. 원본 이미지와 칸 격자를 나란히, conf 낮은 칸 표시, 칸 단위 편집. 통짜 textarea 금지."}
])
```

**확인 완료 전에 첨삭이 도는 경로가 있으면 이 Phase는 실패다.** OCR 오인식과 학생
오류는 기계가 구분할 수 없다. 게이트를 우회할 수 있으면 잘못된 첨삭본이 학생에게 간다.

### Phase I3: 침묵 검증
**모드:** 에이전트 팀 (ocr-dev + corpus-evaluator)

교정 침묵률을 잰다. 골드 코퍼스의 오류 문장을 원고지에 옮겨 쓴 이미지를 넣고, 출력에
그 오류가 **그대로 남아 있는지** 본다. 사라졌으면 OCR이 고친 것이다.

CER과 칸 정렬 정확도도 함께 낸다. **첨삭 F1과 섞지 않는다** — 첨삭 정확도 평가는
언제나 텍스트 입력으로 돈다. 섞으면 F1이 떨어졌을 때 원인을 못 가린다.

## 데이터 흐름

```
레인 C (입력)          레인 B (정확도)              레인 A (출시)
사진 업로드             tests/corpus/*.jsonl   (E1)   01_product-lead_scope.md
  → 칸 스키마    (I1)   _baseline.json         (E2)   engine ↔ frontend
  → 확인 화면    (I2)   05_evaluator_report.md         (api-contract.md)
  → 침묵률·CER   (I3)   04_orthography_rules.md ⇄ 재측정 (E3)
  → 06_ocr-dev_notes.md  지면 밀도 반영         (E4)   03_qa-inspector_report.md
        ↘                      ↓                        ↙
   확인 완료 후에만 → 첨삭 파이프라인 → 검토 → 내보내기
                            ↓
   출시 게이트 (배관 PASS + 정확도 게이트 PASS + OCR 게이트 PASS)
```

**텍스트 붙여넣기는 계속 1급 입력이다.** OCR 경로가 죽어도 앱은 돌아야 한다.

중간 파일 이름: `{phase}_{agent}_{artifact}.md`. `tests/corpus/`는 중간 파일이 아니라
**영구 자산**이므로 `_workspace/`에 두지 않고 아카이브 대상에서도 뺀다.

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 팀원 1명 실패 | 1회 재시작. 재실패 시 리더가 해당 슬라이스를 직접 하거나 재할당. 보고서에 누락 명시 |
| kiwi/폰트 없는 환경 | 레이아웃·게이트 픽스처와 형태소 비의존 규칙만 돌린다. 나머지는 **미검증**으로 남기고 0점으로 적지 않는다 |
| API 계약 충돌 | 삭제하지 않고 양쪽 버전을 노트에 병기한 뒤 product-lead 기준으로 고친다 |
| 정확도가 올랐는데 음성 위반 발생 | **FAIL.** 재현율 상승은 오탐을 정당화하지 않는다. 억제 조건을 붙이고 재측정 |
| 기준선 퇴행을 사용자가 감수하겠다고 함 | 이유를 리포트에 적고 `--update-baseline`. 조용히 덮지 않는다 |
| 코퍼스 검증 실패 | 측정하지 않는다. span이 밀린 코퍼스는 조용히 틀린 점수를 낸다 |
| OCR이 학생 오류를 고쳐서 낸다 | 프롬프트 강화 1회. 그래도 남으면 모델을 바꾸거나 그 유형을 교사 확인 필수로 승격. 침묵률을 실측으로 남긴다 |
| OCR API 키 없음·호출 실패 | 텍스트 입력 경로로 폴백한다. **OCR 실패가 앱을 막지 않는다** |
| 확인 화면 우회 경로 발견 | 즉시 FAIL. 다른 게이트가 다 통과해도 출시 선언하지 않는다 |
| 이미지 보관 정책 미정 | 구현을 멈추고 product-lead에게 묻는다. 개인정보는 나중에 고치기 어렵다 |
| 출시 게이트 과반 실패 | 사용자에게 알리고 출시 선언을 하지 않는다 |

## 테스트 시나리오

### 정상 흐름 (레인 B)
1. "맞춤법 틀린 걸 다 못 잡는다"
2. E1이 유형 태그 붙은 합성 코퍼스를 만들고 검증기를 통과시킨다
3. E2가 O3(조사) 재현율 0.00을 기준선으로 찍는다
4. E3에서 orthography-lead가 받침 조사 규칙을 올리고, evaluator가 O3 0.00→0.95를
   확인하며 다른 유형 F1 유지를 확인한다
5. E4가 늘어난 표기 항목이 지면 상한에 잘리지 않는지 확인한다
6. 기준선 갱신 후 정확도 게이트 PASS 보고

### 에러 흐름 (레인 B)
1. orthography-lead가 되/돼 규칙을 올려 O1 재현율이 오른다
2. 그런데 인용문 안의 구어체를 고치라고 해서 음성 픽스처 위반 2건 발생
3. evaluator가 **FAIL**로 되돌린다. 점수 상승은 이유가 되지 않는다
4. orthography-lead가 따옴표 안 억제 조건을 붙여 재측정, 위반 0건 확인
5. 리포트에 초기 위반과 재검증 통과를 모두 남긴다

### 정상 흐름 (레인 C)
1. "사진으로 올려서 첨삭되게 해줘"
2. I1이 칸 격자 스키마를 못 박고 빈 칸 보존을 계약에 넣는다
3. I2가 업로드 → OCR → 확인 화면을 붙인다. 확인 전에는 첨삭이 돌지 않는다
4. I3이 침묵률 0.94, CER 0.03, 칸 정렬 0.98을 낸다
5. 텍스트 붙여넣기 경로가 그대로 사는지 확인하고 OCR 게이트 PASS 보고

### 에러 흐름 (레인 C)
1. 사진으로 넣은 원고에서 "맞춤법을 하나도 못 잡는다"는 보고가 온다
2. 규칙을 의심하기 전에 **침묵률을 먼저 잰다** → 0.41. OCR이 절반 이상을 고치고 있었다
3. 원인은 규칙 계층이 아니라 입구다. 프롬프트의 verbatim 규칙을 강화한다
4. 재측정 0.93. 같은 원고를 텍스트로 넣었을 때의 F1과 비교해 차이가 사라졌는지 본다
5. 리포트에 "규칙을 고쳤다면 헛수고였을 것"을 남긴다

### 에러 흐름 (레인 A)
1. frontend-dev가 `audience` 없이 export를 호출
2. qa가 계약 불일치를 양쪽에게 알림 → 1회 수정 후 재검증
3. 리포트에 초기 실패와 재검증 통과를 남긴다

## 트리거 검증 (리더용)

Should-trigger: 출시, 시범 운영, 완성도, 입력 화면 붙여, 게이트만 다시, 이전 결과
개선, 출시 전 QA, v1 범위 잠가줘 / 맞춤법을 못 잡는다, 틀린 데를 다 못 찾는다, 없는
오류를 표시한다, 정확도 올려줘, 재현율 측정해줘, 조사 규칙 추가해줘, 코퍼스 만들어줘,
불완전하니 보완해줘, 규칙만 다시 돌려줘 / 사진으로 올리게 해줘, 손글씨 읽어줘,
스캔해서 넣고 싶다, 타이핑하기 귀찮다, OCR 붙여줘, 인식이 자꾸 틀린다.

Should-NOT: 영어 에세이 첨삭 기획, 수능 문항 생성, 이 SVG를 포스터로만 다시 그려,
kiwipiepy 설치 방법만, 커밋 메시지 추천, 일반 FastAPI 튜토리얼, 한글 맞춤법 규정
자체를 설명해달라(교육 질문이지 구현 요청이 아니다).
