# OCR 골드 코퍼스

첨삭 코퍼스(`tests/corpus/*.jsonl`)와 **다른 자산이다.** 여기는 이미지 → 칸 격자를
재고, 저기는 텍스트 → 교정 항목을 잰다. 섞으면 원인을 못 가린다.

## 한 표본 = `{id}.json` + 이미지 파일

```json
{
  "id": "ms3-주장문-001",
  "image": "ms3-주장문-001.jpg",
  "grade": "중학교 3학년",
  "source": "real-handwriting",
  "ncols": 20,
  "gold": [
    "  학교는  단순히  지식을  배우는  곳이",
    "아니라,  여러  친구들과  함께  어울리며"
  ],
  "keep": ["않는다면", "혼스쿨링을"]
}
```

| 필드 | 뜻 |
|------|-----|
| `gold` | 정답 격자. **한 행 정확히 `ncols` 글자, 빈 칸은 공백.** 글자가 없는 뒷행은 빼도 된다 |
| `keep` | 학생이 **틀리게 쓴** 것. OCR이 고치면 침묵률이 깎인다. 원문 그대로 적는다 |

## gold를 만들 때

**고치지 않는다.** 학생이 `학교은`이라고 썼으면 `학교은`으로 적는다. 정답 격자를
교정해 두면 침묵률이 늘 0으로 나오고, 규칙 계층을 헛되이 의심하게 된다.

**칸을 세서 적는다.** 한 칸이 밀린 정답 격자는 조용히 틀린 점수를 낸다. 눈으로
훑지 말고 이미지를 행 단위로 잘라 확대해서 센다.

## 재는 법

```
python .claude/skills/wongoji-eval/scripts/eval_ocr.py
python .claude/skills/wongoji-eval/scripts/eval_ocr.py --save-pred /tmp/ocr
python .claude/skills/wongoji-eval/scripts/eval_ocr.py --offline /tmp/ocr/pred.json
```

## 개인정보

실제 학생 원고 이미지는 이름·학교·지명을 가린 뒤에만 넣는다. `.gitignore`가
`tests/corpus/ocr/*.jpg`를 막고 있는지 확인하고 커밋한다.
