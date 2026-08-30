---
name: wongoji-engine
description: "원고지 첨삭 엔진과 FastAPI를 구현·수정한다. 규칙/LLM 계층, 검증 게이트, 파이프라인 단일화, wongoji_render 칸 좌표, SVG 빌드, 세션 저장, /api/chumsak·export·session, Anthropic 호스트, 레이아웃 테스트, 층위별 지면 상한, 원고지 장 나눔과 범례·총평 지면. 엔진·게이트·렌더러·서버를 만지거나 부호 위치가 틀렸다는 보고가 오면, 또는 잡은 오류가 지면에 안 그려진다는 보고가 오면 반드시 사용. UI 색만 바꾸는 작업에는 쓰지 않는다."
---

# 첨삭 엔진

칸 좌표의 단일 출처는 `wongoji_render.py`다. `wongoji_svg.py`는 `export_layout()`을 소비하고 부호 모양만 그린다. 서버는 게이트를 다시 조립하지 않는다.

도메인 판단은 `wongoji-domain`을 읽는다. API 필드 세부는 `references/api-contract.md`를 읽는다.

## 파이프라인 단일화

`chumsak_app`에 조립 함수 하나를 둔다.

```
rules = rule_layer(text, kiwi)
llm, review, refused = llm_layer(...) if host else ([], {}, [])
llm, bogus = normalize(text, llm)
merged, dropped = verify(text, dedupe(rules + llm))
merged, clashed = drop_overlaps(merged)
drawn, held = focus_filter(merged, focus, max_items)
```

`server.run_pipeline`과 `chumsak()`는 이 함수를 호출한다. host가 None이면 LLM을 건너뛴다. `chumsak()`가 host를 필수값으로 두면 라이브러리 경로가 서버와 어긋난다.

렌더 분기:
- 웹 검토: `wongoji_svg.build(spec)` → SVG + data
- 파일 산출: `wongoji_render.render(spec)` → PNG/PDF

## 반드시 고치는 엔진 결함

마지막 문장 종결부호: `split_into_sents` 결과의 **마지막 문장도** 본다. 글 전체가 마침표 없이 끝나면 그것이 가장 눈에 띄는 오류다.

겹침: 규칙 계층이 이기는 것은 맞다. 그러나 구간이 한 글자라도 겹친다고 LLM 항목을 전부 버리면 이웃한 다른 종류의 내용 첨삭이 사라진다. 같은 자리·같은 경계, 또는 규칙 span이 LLM span을 실질적으로 덮을 때만 반려한다.

들여쓰기와 stet: `spec["indent"]`는 "원문을 들여 그릴지"다. 들여쓰기표가 **승인되어 오류를 가리킬 때**만 indent=0이다. 기각되어 kind가 `stet`가 되면 원문 배치(indent=0, 첫 칸 채움)를 유지한 채 되살림표를 그린다. indent=1로 바꾸면 오류가 화면에 없어진다.

## 층위별 지면 상한

제품 결정: **표기(layer=표기)는 전수 표시, 내용(layer=내용)만 초점 상한.**

`focus_filter`가 종류를 라운드로빈으로 돌며 `MAX_SHEET_ITEMS`에서 자르면, 맞춤법
오류가 상한에 걸려 사라진다. "틀린 곳을 다 찾아 준다"는 약속이 여기서 깨진다.

```
표기 = [c for c in merged if c.get("layer") == "표기"]
내용 = [c for c in merged if c.get("layer") != "표기"]
drawn = 표기 + focus_filter(내용, focus=focus, max_items=MAX_CONTENT_ITEMS)[0]
```

지면이 모자라면 항목을 버리는 대신 `nrows`를 늘리거나 장을 나눈다. 진짜 상한은
숫자 16이 아니라 **부호가 겹쳐 못 읽히는 지점**이다.

`layer` 필드가 정확해야 이 분기가 산다. 규칙 항목은 `make()` 기본값에 기대지 말고
유형마다 `layer`와 `type`(O1~O10, C1~C4)을 명시한다. `type`이 없으면 정확도 평가가
그 항목을 유형 미상으로 세어 리포트가 쓸모없어진다.

**진단법:** `eval_accuracy.py`를 `--held` 없이 한 번, 붙여서 한 번 돌린다. 두 점수
차이가 크면 엔진은 찾았는데 이 분기가 잘라낸 것이다. 고칠 곳은 규칙이 아니라 여기다.

## 지면 운용 (PNG·PDF)

**호출측이 nrows를 어림하지 않는다.** `2 * lines + 4` 같은 추정은 실제 배치와 어긋나
열 줄 넘게 빈 원고지를 만든다. 행 수는 렌더러가 배치를 마친 뒤 `paginate()`로 정한다.

| 규칙 | 이유 |
|------|------|
| 한 장 = `SHEET_ROWS`(기본 20행) | double_space면 원고 10행 = 200자 원고지 한 장 |
| 마지막 장도 온전한 한 장 | 원고지는 남는 칸이 있는 채로 끝나는 것이 정상이다 |
| **빈 장은 만들지 않는다** | 쓰이지 않은 장을 그리면 학생이 받는 종이가 늘어난다 |
| PDF는 진짜 페이지로 나눈다 | 인쇄해야 하는 산출물이다. 한 장짜리 긴 그림은 인쇄가 안 된다 |
| PNG는 장을 세로로 잇고 쪽 번호를 단다 | 화면에서는 스크롤이 자연스럽다 |
| 교정 내용·총평은 PDF에서 별도 장 | 학생이 원고와 나란히 놓고 본다 |

`export_layout`도 같은 `paginate()`를 쓴다. SVG와 PNG가 다른 행 수를 그리면 칸 좌표의
단일 출처가 깨진다.

## 축 좌표계의 단위를 섞지 않는다

지면 버그는 대부분 **인치와 축 비율을 섞어서** 난다. 실제로 세 번 났다.

- 범례·총평의 줄 높이를 그림 인치로 계산해 축 비율 좌표에 그대로 썼다. 지면이 길수록
  축은 짧아지는데 줄 간격은 그대로여서 **글자가 겹쳤다.** 축 안에서
  `set_ylim(panel_h, 0)`으로 y를 인치로 두어 없앴다
- 격자 축에는 `aspect="equal"`이 걸려 있다. rect 높이를 임의로 주면 matplotlib이 축을
  줄이고 위아래에 슬랙을 남긴다. 그 슬랙이 제목과 격자 사이의 빈 띠였다.
  `sheet_inches()`로 비율에서 높이를 역산한다
- 번호표 원을 축 비율 폭으로 그리면 지면이 길어질 때 가로로 늘어나 라벨을 덮는다.
  글자 크기를 따라가는 `bbox=dict(boxstyle="circle")`을 쓴다

기하를 만졌으면 PNG와 PDF를 같은 spec으로 내고 **눈으로 본다.** 겹침은 테스트가 잡지
못한다. `tests/test_layout.py`는 장 나눔과 패널 높이 증가만 지킨다.

## LLM 호스트

환경변수 `ANTHROPIC_API_KEY`가 있으면 `llm_anthropic.Host`를 쓴다. `CHUMSAK_NO_LLM=1`이면 끈다. `import host` / `builtins.host`는 보조 주입일 뿐 기본 경로가 아니다.

구조화 출력은 tool_use `submit_chumsak`만 신뢰한다. 본문 텍스트 JSON은 파싱하지 않는다.

프롬프트에 **규칙 계층이 이미 잡은 유형 코드 목록**을 넣는다. 이 정보가 없으면 LLM이
띄어쓰기를 중복 제출하고, 그것이 `drop_overlaps`에서 버려지면서 정작 필요한 내용
첨삭 자리를 잡아먹는다. 규칙으로 판정 가능한 표기 오류는 LLM의 일이 아니다
(`wongoji-orthography` 참조).

## 세션과 검증

- 세션은 디스크에 둔다 (`data/sessions/`). 메모리 dict만 있으면 재시작과 동시 사용에 진다
- 본문 길이 상한을 둔다 (기본 4000자, 200자 원고지 약 20매)
- export는 승인·수정은 그리고, 기각은 stet, 미검토는 제외. 학생용 PDF는 미검토가 있으면 400

## 테스트

`tests/test_layout.py`: `examples/spec_예시.json`을 `export_layout`에 넣어 부호 n별 앵커 종류·행이 픽스처와 같아야 한다. kiwipiepy 없이 돈다.

`tests/test_gate.py`: 실행결과 JSON의 dropped 사유 유형(target 없음, 범위 과대, 문장 통째, 삽입 과장, 교사 전용 부호)을 함수 단위로 재현한다.

정확도 회귀는 `wongoji-eval`의 `eval_accuracy.py`가 본다. 파이프라인·상한·병합을
만졌으면 레이아웃 테스트뿐 아니라 정확도 게이트도 돌린다. 조립 순서를 바꾸면 점수가
조용히 떨어진다.

한 규칙만 고치고 렌더러 기하를 다시 쓰지 않는다. 기하를 만지면 PNG와 SVG를 같은 spec으로 비교한다.

## 테스트 프롬프트

1. "서버와 chumsak()가 게이트를 두 번 조립하지 않게 한 함수로 모아줘"
2. "마지막 문장에 마침표가 없을 때 punct가 나오게 해줘"
3. "기각한 들여쓰기표가 본문을 한 칸 들여 버리지 않게 해줘"
---
