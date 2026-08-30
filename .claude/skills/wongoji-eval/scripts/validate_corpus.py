# -*- coding: utf-8 -*-
"""골드 코퍼스가 스키마를 지키는지, span이 본문과 맞는지 검사한다.

    python .claude/skills/wongoji-eval/scripts/validate_corpus.py tests/corpus

span이 한 칸이라도 밀리면 평가 전체가 조용히 틀린다. 코퍼스를 손으로 늘린 뒤에는
반드시 이걸 먼저 돌린다.
"""
import json
import os
import sys

TYPES = {"O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8", "O9", "O10", "O11",
         "C1", "C2", "C3", "C4"}
KINDS = {"space", "join", "insert", "punct", "delete", "replace", "swap",
         "indent", "outdent", "newline", "joinline", "up", "down", "stet"}


def check(path):
    problems, ids, count = [], set(), 0
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            where = "%s:%d" % (os.path.basename(path), lineno)
            try:
                rec = json.loads(line)
            except ValueError as exc:
                problems.append("%s JSON 파싱 실패: %s" % (where, exc))
                continue
            count += 1
            rid = rec.get("id")
            if not rid:
                problems.append("%s id가 없다" % where)
            elif rid in ids:
                problems.append("%s id 중복: %s" % (where, rid))
            else:
                ids.add(rid)
            text = rec.get("text")
            if not isinstance(text, str) or not text.strip():
                problems.append("%s text가 비었다" % where)
                continue
            if not rec.get("errors") and not rec.get("negatives"):
                problems.append("%s errors와 negatives가 둘 다 없다" % where)
            for label in ("errors", "negatives"):
                for i, item in enumerate(rec.get(label, [])):
                    tag = "%s %s[%d]" % (where, label, i)
                    t = item.get("type")
                    if t not in TYPES:
                        problems.append("%s 알 수 없는 type: %r" % (tag, t))
                    sp = item.get("span")
                    if (not isinstance(sp, list) or len(sp) != 2
                            or not all(isinstance(v, int) for v in sp)):
                        problems.append("%s span이 [시작,끝] 정수쌍이 아니다" % tag)
                        continue
                    s, e = sp
                    if not (0 <= s < e <= len(text)):
                        problems.append("%s span 범위 이탈 %s (본문 %d자)"
                                        % (tag, sp, len(text)))
                        continue
                    frag = text[s:e]
                    quoted = item.get("target")
                    if quoted is not None and quoted != frag:
                        problems.append("%s target %r != 본문 %r" % (tag, quoted, frag))
                    if label == "errors":
                        k = item.get("kind")
                        if k not in KINDS:
                            problems.append("%s 알 수 없는 kind: %r" % (tag, k))
                        if k in ("replace", "insert", "punct") and not item.get("fix"):
                            problems.append("%s %s인데 fix(고칠 글자)가 없다" % (tag, k))
    return problems, count


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "tests/corpus"
    files = []
    if os.path.isdir(target):
        files = [os.path.join(target, n) for n in sorted(os.listdir(target))
                 if n.endswith(".jsonl") and not n.startswith("_")]
    elif os.path.exists(target):
        files = [target]
    if not files:
        raise SystemExit("코퍼스 파일이 없다: %s" % target)
    allp, total = [], 0
    for f in files:
        p, c = check(f)
        allp += p
        total += c
        print("%s  레코드 %d, 문제 %d" % (f, c, len(p)))
    if allp:
        print("\n문제 %d건" % len(allp))
        for line in allp:
            print("  - " + line)
        sys.exit(1)
    print("\n레코드 %d편 전부 스키마 통과" % total)


if __name__ == "__main__":
    main()
