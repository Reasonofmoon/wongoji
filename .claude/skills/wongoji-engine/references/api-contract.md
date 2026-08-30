# API 계약

프론트와 엔진이 함께 잠그는 필드. 이름·의미가 바뀌면 양쪽을 같이 고친다.

## POST /api/chumsak

요청:

```json
{
  "text": "학생 원문",
  "grade": "초등 6학년",
  "focus": ["space", "punct"],
  "indirect": false,
  "llm_items": 6
}
```

`focus` null/생략 = 부호 종류 제한 없음. `indirect` true면 insert/punct/replace의 text를 □로 가린다.

응답:

```json
{
  "session": "hex12",
  "svg": "<svg ...>",
  "data": {
    "grid": {"ncols": 20, "nrows": 14, "gap_after": 10, "gap": 0.16},
    "cells": [{"r": 0, "c": 0, "tok": "어", "src": [0, 1]}],
    "corrections": [{
      "n": 1, "kind": "space", "label": "띄움표",
      "reason": "...", "layer": "표기", "source": "rule",
      "severity": "보통", "target": "친구와", "nth": 0,
      "text": null, "state": "pending",
      "anchor": {"type": "boundary", "r": 1, "c": 5}
    }],
    "review": {"good": "", "fix": "", "next": ""},
    "meta": {"text": "...", "title": null, "figure_title": "...", "caption": "..."}
  },
  "gate": [{"kind": "...", "target": "...", "reason": "...", "drop_reason": "...", "source": "llm"}],
  "counts": {"rule": 0, "llm": 0, "drawn": 0, "held": 0, "dropped": 0},
  "elapsed_s": 0.12
}
```

## GET /api/session?id=

`id`가 있으면 그 세션. 없으면 가장 최근. 세션이 전무하면 데모 원고로 하나 만든다.

응답 shape는 `/api/chumsak`와 같다.

## POST /api/export

요청:

```json
{
  "text": "원문",
  "corrections": [{
    "kind": "space", "target": "친구와", "nth": 0, "text": null,
    "reason": "...", "layer": "표기", "source": "rule", "state": "approved"
  }],
  "review": {"good": "", "fix": "", "next": ""},
  "format": "png",
  "audience": "teacher"
}
```

`audience`: `teacher` (PNG 미리보기, 미검토 제외하고 그림) | `student` (PDF, 미검토 있으면 400).

성공: `{url, file, approved, stet, unresolved}`. 실패: `{error}` + 4xx.

## GET /api/health

`{ok, llm, sessions, persist}` — `llm`은 호스트 주입 여부, `persist`는 디스크 세션 사용 여부.
---
