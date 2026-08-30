# -*- coding: utf-8 -*-
"""골드 코퍼스로 첨삭 엔진의 표기 오류 탐지 정확도를 측정한다.

    python .claude/skills/wongoji-eval/scripts/eval_accuracy.py
    python ... --corpus tests/corpus --llm --baseline tests/corpus/_baseline.json
    python ... --update-baseline

정밀도(precision)  잡은 것 중 진짜 오류의 비율. 낮으면 교사가 신뢰를 잃는다.
재현율(recall)     진짜 오류 중 잡은 것의 비율. 낮으면 "다 찾아 준다"가 거짓말이 된다.

유형별로 쪼개서 낸다. 총점만 보면 어떤 규칙이 죽었는지 알 수 없다.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

TOLERANCE = 1          # 경계 부호는 한 칸 어긋나도 같은 자리로 본다
BOUNDARY = ("space", "insert", "punct", "newline", "joinline")


def load_corpus(path):
    """디렉토리 또는 단일 .jsonl에서 골드 레코드를 읽는다."""
    files = []
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.endswith(".jsonl") and not name.startswith("_"):
                files.append(os.path.join(path, name))
    else:
        files = [path]
    records = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError as exc:
                    raise SystemExit("%s:%d 파싱 실패: %s" % (f, lineno, exc))
    return records


def predict(text, grade, use_llm):
    """엔진을 돌려 지면 항목 + 보류 항목을 (span, kind, type) 목록으로 만든다."""
    import chumsak_app as CA
    kiwi = None
    try:
        from kiwipiepy import Kiwi
        kiwi = Kiwi()
    except Exception:
        pass
    rules = CA.rule_layer(text, kiwi) if kiwi else []
    llm, refused = [], []
    if use_llm:
        import llm_host as LH
        for _provider, host in LH.iter_hosts():
            try:
                llm, _review, refused = CA.llm_layer(text, host, grade=grade)
                break
            except Exception:
                continue
    drawn, held, _dropped = CA.assemble(text, rules, llm, refused=refused)
    out = []
    for c in drawn:
        sp = c.get("_span") or CA.span_of(text, c)
        if sp:
            out.append({"span": list(sp), "kind": c["kind"],
                        "type": c.get("type"), "drawn": True,
                        "reason": c.get("reason", "")})
    for c in held:
        sp = c.get("_span") or CA.span_of(text, c)
        if sp:
            out.append({"span": list(sp), "kind": c["kind"],
                        "type": c.get("type"), "drawn": False,
                        "reason": c.get("reason", "")})
    return out


# insert와 punct는 normalize()가 서로 바꾸므로 같은 부호로 본다. 그 밖은 정확히 같아야
# 한다. 자리만 맞고 부호가 다르면 학생은 엉뚱한 지시를 받는다 — 정답으로 세지 않는다.
KIND_EQUIV = [{"insert", "punct"}]


def same_kind(a, b):
    if a == b:
        return True
    return any(a in g and b in g for g in KIND_EQUIV)


def at_same_place(pred_span, gold_span, kind):
    """두 구간이 같은 자리를 가리키는지. 경계 부호는 한 칸 허용 오차를 둔다."""
    ps, pe = pred_span
    gs, ge = gold_span
    if kind in BOUNDARY:
        return abs(pe - ge) <= TOLERANCE or abs(ps - gs) <= TOLERANCE
    return ps < ge and gs < pe


def hits(pred, gold):
    """정답으로 인정하려면 자리와 부호가 모두 맞아야 한다.

    자리만 보고 인정하면 띄어쓰기 제안이 조사 오류의 정답으로 둔갑한다. 그러면
    정밀도가 실제보다 높게 나오고, 하네스가 거짓 안심을 준다.
    """
    gk = gold.get("kind", pred["kind"])
    if not same_kind(pred["kind"], gk):
        return False
    if pred.get("type") and pred["type"] != gold.get("type"):
        return False
    return at_same_place(pred["span"], gold["span"], gk)


def score(records, use_llm, drawn_only):
    """유형별 TP/FP/FN과 음성 픽스처 위반을 센다."""
    stat = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    violations, misses, extras = [], [], []
    for rec in records:
        text = rec["text"]
        preds = predict(text, rec.get("grade", "초등 6학년"), use_llm)
        if drawn_only:
            preds = [p for p in preds if p["drawn"]]
        gold = rec.get("errors", [])
        negatives = rec.get("negatives", [])
        used = set()
        for gi, g in enumerate(gold):
            found = None
            for pi, p in enumerate(preds):
                if pi in used:
                    continue
                if hits(p, g):
                    found = pi
                    break
            if found is None:
                stat[g["type"]]["fn"] += 1
                misses.append((rec["id"], g["type"], text[g["span"][0]:g["span"][1]]))
            else:
                used.add(found)
                stat[g["type"]]["tp"] += 1
        for pi, p in enumerate(preds):
            if pi in used:
                continue
            bucket = p.get("type") or ("?" + p["kind"])
            stat[bucket]["fp"] += 1
            extras.append((rec["id"], bucket, text[p["span"][0]:p["span"][1]],
                           p.get("reason", "")[:40]))
            for n in negatives:
                if at_same_place(p["span"], n["span"], p["kind"]):
                    violations.append((rec["id"], n.get("note", ""),
                                       "%s '%s'" % (p["kind"],
                                                    text[p["span"][0]:p["span"][1]])))
    return stat, violations, misses, extras


def prf(cell):
    tp, fp, fn = cell["tp"], cell["fp"], cell["fn"]
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def report(stat, violations, misses, extras, baseline, show):
    rows = sorted(stat.items())
    total = {"tp": 0, "fp": 0, "fn": 0}
    for _t, c in rows:
        for k in total:
            total[k] += c[k]
    print("유형   정밀도  재현율   F1    TP  FP  FN")
    print("-" * 44)
    for t, c in rows:
        p, r, f = prf(c)
        mark = ""
        if baseline and t in baseline:
            delta = f - baseline[t]
            if delta < -0.01:
                mark = "  ↓퇴행 %.2f" % delta
            elif delta > 0.01:
                mark = "  ↑%.2f" % delta
        print("%-6s %5.2f  %5.2f  %5.2f  %3d %3d %3d%s"
              % (t, p, r, f, c["tp"], c["fp"], c["fn"], mark))
    print("-" * 44)
    p, r, f = prf(total)
    print("%-6s %5.2f  %5.2f  %5.2f  %3d %3d %3d"
          % ("전체", p, r, f, total["tp"], total["fp"], total["fn"]))

    if violations:
        print("\n음성 픽스처 위반 (잡으면 안 되는 것을 잡았다) — %d건" % len(violations))
        for rid, note, what in violations[:show]:
            print("  %s  %s  <- %s" % (rid, what, note))
    if misses:
        print("\n놓친 오류 %d건 (재현율 손실)" % len(misses))
        for rid, t, frag in misses[:show]:
            print("  %s  [%s] '%s'" % (rid, t, frag))
    if extras:
        print("\n헛짚음 %d건 (정밀도 손실)" % len(extras))
        for rid, t, frag, why in extras[:show]:
            print("  %s  [%s] '%s'  %s" % (rid, t, frag, why))
    # '?'로 시작하는 칸은 유형이 없는 헛짚음 모음이라 기준선이 될 수 없다.
    return {t: prf(c)[2] for t, c in rows if not t.startswith("?")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="tests/corpus")
    ap.add_argument("--llm", action="store_true", help="LLM 계층까지 포함해 측정")
    ap.add_argument("--held", action="store_true",
                    help="지면 항목뿐 아니라 보류 항목도 정답으로 인정")
    ap.add_argument("--baseline", default="tests/corpus/_baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--show", type=int, default=15)
    ap.add_argument("--gate", type=float, default=None,
                    help="전체 F1이 이 값 미만이면 실패로 종료한다")
    args = ap.parse_args()

    corpus = os.path.join(ROOT, args.corpus) if not os.path.isabs(args.corpus) else args.corpus
    if not os.path.exists(corpus):
        raise SystemExit("코퍼스가 없다: %s — wongoji-eval 스킬의 생성 절차를 먼저 돈다" % corpus)
    records = load_corpus(corpus)
    if not records:
        raise SystemExit("코퍼스가 비어 있다: %s" % corpus)
    print("코퍼스 %d편, LLM 계층 %s, 보류항목 %s\n"
          % (len(records), "포함" if args.llm else "제외",
             "인정" if args.held else "제외"))

    base_path = os.path.join(ROOT, args.baseline) if not os.path.isabs(args.baseline) else args.baseline
    baseline = None
    if os.path.exists(base_path) and not args.update_baseline:
        with open(base_path, encoding="utf-8") as fh:
            baseline = json.load(fh)

    stat, violations, misses, extras = score(records, args.llm, not args.held)
    current = report(stat, violations, misses, extras, baseline, args.show)

    if args.update_baseline:
        with open(base_path, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print("\n기준선 갱신: %s" % base_path)
        return

    failed = []
    if baseline:
        for t, f in current.items():
            if t in baseline and f < baseline[t] - 0.01:
                failed.append("%s F1 %.2f < 기준선 %.2f" % (t, f, baseline[t]))
    if violations:
        failed.append("음성 픽스처 위반 %d건" % len(violations))
    if args.gate is not None:
        tot = sum(c["tp"] for c in stat.values()), sum(c["fp"] for c in stat.values()), \
              sum(c["fn"] for c in stat.values())
        cell = {"tp": tot[0], "fp": tot[1], "fn": tot[2]}
        if prf(cell)[2] < args.gate:
            failed.append("전체 F1 %.2f < 게이트 %.2f" % (prf(cell)[2], args.gate))
    if failed:
        print("\n정확도 게이트 FAIL")
        for line in failed:
            print("  - " + line)
        sys.exit(1)
    print("\n정확도 게이트 PASS")


if __name__ == "__main__":
    main()
