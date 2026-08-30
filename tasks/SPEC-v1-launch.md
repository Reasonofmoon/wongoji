# SPEC — 원고지 첨삭기 v1 출시

날짜: 2026-08-30  
범위: 교사용 웹 1단계 (한 학급 시범 운영)

## 목표

교사가 학생 글을 붙여넣고, 원고지 위에 앉은 교정부호를 승인·수정·기각한 뒤, 인쇄 가능한 PNG/PDF를 받는다. 점수는 없다.

## 사용자 여정

1. 입력 화면에서 원문·학년·초점(최대 2종)·간접 첨삭을 고른다
2. 실행 → 규칙 계층은 즉시, LLM은 키가 있을 때만
3. 검토 화면에서 부호와 목록을 오가며 처리한다
4. 총평 3단을 손질한다
5. PNG(교사 미리보기) 또는 PDF(학생에게 돌려주기)

## 넣는 것 / 빼는 것

**넣는다:** 붙여넣기 입력, 단일 파이프라인, 게이트, 검토 UX(대체 글자 수정 포함), 디스크 세션, 길이 제한, LLM 키 자동 연결, 레이아웃·게이트 테스트, README 한 줄 실행.

**뺀다:** 점수, 실시간 교정, OCR, 학급/로그인, hunspell, Next.js·Supabase 재작성, 회차 비교.

스택 결정: 엔진이 kiwipiepy·matplotlib이라 v1은 FastAPI + 바닐라 JS 모놀리스.

## 출시 게이트

- [x] 데모 문장에 갇히지 않고 새 글을 붙여넣을 수 있다
- [x] `examples/spec_예시.json` 앵커 테스트 통과
- [x] 마지막 문장 종결부호 누락이 잡힌다
- [x] 기각된 들여쓰기가 원문 배치를 밀어 쓰지 않는다
- [x] 파이프라인 조립은 `chumsak_app` 한곳
- [x] UI·PDF에 점수/등급이 없다
- [x] `uvicorn server:app --port 8000`으로 로컬 실행된다

## 기술 설계

- `assemble()`이 정규화·검증·겹침·초점을 담당. 서버는 호출만
- 세션: `data/sessions/{id}.json`
- API 계약: `.claude/skills/wongoji-engine/references/api-contract.md`
- 레이아웃 indent는 원문 첫 칸을 따른다

## 테스트

- `tests/test_layout.py` — 좌표, kiwi 불필요
- `tests/test_gate.py` — 반려 사유 유형
- 관련 파일만 실행
---
