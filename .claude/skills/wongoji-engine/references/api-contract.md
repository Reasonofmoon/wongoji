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

## POST /api/ocr  (multipart)

`files`: 원고지 사진 여러 장. 파일명 자연 정렬(1, 2, 10)로 페이지 순서를 정한다.
장당 8MB, 한 번에 12장까지.

응답:

```json
{
  "ocr_id": "529803ca238a",
  "ncols": 20,
  "pages": [{"page": 1, "ncols": 20, "rows": [
    {"row": 1, "cells": "동생가 아이스크림를 먹었다 ", "conf": 0.95, "uncertain": []}]}],
  "low_conf": [{"page": 1, "row": 2, "col": 4, "ch": "", "conf": 0.0, "why": "읽지 못한 칸"}],
  "warnings": ["1쪽: 격자를 넘어 쓴 글자"],
  "confirmed": false
}
```

**`text`가 없는 것이 게이트다.** 본문은 확인을 지나야 나온다. `cells`는 정확히
`ncols` 글자이고 빈 칸은 공백 한 자다. 빈 칸을 버리면 문단 첫 칸 오류가 사라진다.

인식 실패: `{error, detail}` + 502. 이때 붙여넣기 입력은 그대로 살아 있어야 한다.
업로드한 이미지는 디스크에 남기지 않는다.

## POST /api/ocr/confirm

요청: `{"ocr_id": "...", "pages": [{"page": 1, "rows": [{"row": 1, "cells": "..."}]}]}`

교사가 고친 칸을 받아 본문을 확정한다. **여기서만 `text`가 나온다.**

응답: `{ocr_id, text, confirmed: true, chars}`. 빈 본문·초과 길이는 400.

## POST /api/chumsak — `ocr_id`

`ocr_id`를 함께 보내면 서버는 **확인된 본문만** 쓰고 클라이언트가 보낸 `text`는 버린다.
확인 전이면 409, 없는 id면 404. 사진에서 온 원고를 확인 없이 첨삭하면 OCR 오인식이
학생 오류로 지적되는데, 그 구분은 기계가 할 수 없다.
