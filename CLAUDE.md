# 원고지 첨삭기

한국어 학생 글을 원고지 격자 위에 교정부호로 첨삭하는 교사용 웹. 점수를 매기지 않는다. 산출물은 인쇄 가능한 첨삭본이다.

## 하네스: 원고지 첨삭기 출시

**목표:** 프로토타입을 한 학급 시범 운영이 가능한 교사용 웹(v1)으로 올린다.

**트리거:** 출시, 시범 운영, 완성도, v1 구현, 엔진/UI/QA, 입력 화면, 게이트, 범위 잠금, 그리고 맞춤법 정확도, 오류를 못 잡는다, 오탐, 재현율, 규칙 추가, 코퍼스, 평가, 불완전하다 등 이 앱을 키우는 작업이면 `wongoji-orchestrator` 스킬을 사용하라. 단순 질문은 직접 응답 가능.

**레인:** A(출시 = 쓸 수 있는가) / B(정확도 = 믿을 수 있는가) / C(입력 = 시작할 수 있는가). 순서는 C → B → A.

**OCR 원칙:** OCR이 맞춤법을 고치면 첨삭기는 죽는다. 사진으로 넣은 원고에서 "못 잡는다"는 보고가 오면 규칙보다 **교정 침묵률**을 먼저 잰다. 교사 확인 화면을 거치기 전에는 첨삭을 돌리지 않는다.

**정확도 원칙:** 측정이 구현보다 먼저다. 기준선(`tests/corpus/_baseline.json`) 없이 규칙을 고치지 않는다. 표기 오류는 전수 표시, 내용 첨삭만 지면 상한.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-08-30 | 초기 구성 | 전체 | 출시 하네스 신규 구축. 에이전트 4(product-lead, engine-dev, frontend-dev, qa-inspector), 스킬 6(orchestrator/product/engine/frontend/qa/domain) |
| 2026-08-30 | 정확도 레인 증설 | agents/orthography-lead, agents/corpus-evaluator, skills/wongoji-orthography, skills/wongoji-eval | 맞춤법 오류를 다 못 잡는다는 보고. 결정적 규칙이 3종뿐이고 정확도를 측정할 수단이 없었다 |
| 2026-08-30 | 첨삭 밀도 정책 확정 | skills/wongoji-product, skills/wongoji-engine | 표기는 전수, 내용만 초점 상한. 지면 상한이 맞춤법 오류를 잘라내던 문제 |
| 2026-08-30 | 정확도 게이트 합류 | skills/wongoji-qa, skills/wongoji-orchestrator | QA가 배관만 보고 '실패 없음'을 내던 문제. 출시 게이트에 유형별 회귀·오탐 게이트 추가 |
| 2026-08-30 | 말뭉치 실측 반영 | skills/wongoji-orthography(references/말뭉치_근거.md, O11 추가), skills/wongoji-eval | 오류 796건 실측 분포로 규칙 우선순위 재배치. 혼동쌍 목록 전제가 반증됨(표기 83%가 자모 1개 차이, 반복 짝 0종) |
| 2026-08-30 | 밀도 정책 드리프트 수정 | skills/wongoji-domain | '초점 첨삭이 기본이고 항목 수 상한이 있다'가 새 정책과 충돌. 부호 14종 CSV도 references에 추가 |
| 2026-08-30 | **OCR 범위 반전** — 2단계 → v1 필수 | skills/wongoji-product, agents/product-lead | 사용자 지시. 한 학급 25명 재타이핑이면 입력이 첨삭보다 오래 걸려 시범 운영이 입구에서 막힌다 |
| 2026-08-30 | 입력 레인 증설 | agents/ocr-dev, skills/wongoji-ocr, skills/wongoji-orchestrator(레인 C) | 비전 모델 OCR. 칸 좌표 보존·자동 교정 금지·교사 확인 게이트를 조건으로 잠금 |
| 2026-08-30 | OCR 게이트 분리 | skills/wongoji-eval, skills/wongoji-qa, skills/wongoji-frontend | 첨삭 F1과 OCR 지표(CER·칸 정렬·교정 침묵률)를 섞으면 원인을 못 가린다 |
---
