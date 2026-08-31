# -*- coding: utf-8 -*-
"""OCR 지표. 첨삭 F1과 절대 섞지 않는다.

섞으면 점수가 떨어졌을 때 규칙 탓인지 OCR 탓인지 못 가리고, 멀쩡한 맞춤법 규칙을
헛되이 고치게 된다. 첨삭 정확도는 언제나 텍스트 입력으로 잰다(eval_accuracy.py).

지표 넷:
  교정 침묵률   OCR이 학생 오류를 고치지 않고 그대로 낸 비율. 이 앱 고유의 핵심 지표
  칸 정렬 정확도 글자가 올바른 (행, 칸)에 놓인 비율. 여기가 깨지면 O8이 죽는다
  CER          문자 오류율. 편집거리 / 정답 길이
  행 길이 위반률 모델이 ncols를 지키지 못한 행의 비율. '세기 부담'의 직접 측정치

CER이 0이어도 칸이 밀리면 첨삭은 틀린다. 그래서 넷을 따로 낸다.

쓰는 법:
  python eval_ocr.py                    # tests/corpus/ocr/ 전체를 실모델로
  python eval_ocr.py --id hs-001        # 한 편만
  python eval_ocr.py --offline pred.json  # 저장된 예측을 다시 채점(호출 없음)
  python eval_ocr.py --save-pred out/    # 예측을 남겨 두고 나중에 재채점
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
for _ in range(6):                       # 저장소 뿌리를 찾아 올라간다
    if os.path.isfile(os.path.join(ROOT, "ocr_wongoji.py")):
        break
    ROOT = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

CORPUS = os.path.join(ROOT, "tests", "corpus", "ocr")


# ---------------------------------------------------------------- 편집거리
def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------- 지표
def cer(gold_text, pred_text):
    if not gold_text:
        return 0.0 if not pred_text else 1.0
    return levenshtein(gold_text, pred_text) / len(gold_text)


def cell_alignment(gold_rows, pred_rows, ncols):
    """글자가 올바른 (행, 칸)에 놓였는가.

    글자가 있는 행만 센다. 뒤쪽 빈 행을 포함하면 아무것도 안 읽어도 점수가 높게 나온다.
    정답 격자의 `?`는 사람이 판정하지 못한 칸이다. 추측한 정답으로 점수를 내면
    조용히 틀린 수치가 나오므로 세지 않는다.
    """
    by_row = {i + 1: r for i, r in enumerate(pred_rows)}
    hit = total = 0
    misses = []
    for i, gold in enumerate(gold_rows, 1):
        if not gold.strip():
            continue
        pred = (by_row.get(i) or "").ljust(ncols)[:ncols]
        gold = gold.ljust(ncols)[:ncols]
        for col in range(ncols):
            if gold[col] == "?":
                continue          # 사람이 판정하지 못한 칸은 점수에서 뺀다
            total += 1
            if gold[col] == pred[col]:
                hit += 1
            elif len(misses) < 40:
                misses.append((i, col + 1, gold[col], pred[col]))
    return (hit / total if total else 0.0), total, misses


def silence_rate(keep, pred_text):
    """학생이 틀리게 쓴 것이 그대로 살아남았는가. 사라졌으면 OCR이 고친 것이다."""
    if not keep:
        return None, []
    survived = [k for k in keep if k in pred_text]
    lost = [k for k in keep if k not in pred_text]
    return len(survived) / len(keep), lost


def row_length_violation(notes, nrows):
    """정규화가 자르거나 채운 행의 수 / 전체 행. 잘리기 전에 세야 한다."""
    hits = [n for n in notes if "칸으로 왔다" in n]
    return (len(hits) / nrows if nrows else 0.0), hits


# ---------------------------------------------------------------- 실행
def rows_to_text(rows, ncols):
    """칸 격자 -> 본문. 엔진과 같은 규칙을 쓴다."""
    import ocr_wongoji as OCR
    page = {"page": 1, "ncols": ncols,
            "rows": [{"row": i + 1, "cells": c} for i, c in enumerate(rows)]}
    return OCR.grid_to_text([page], ncols)


def predict(sample, model=None):
    """실모델 호출. 반환은 (행 문자열 목록, 경고 목록, provider)."""
    import llm_host as LH
    import ocr_wongoji as OCR
    path = os.path.join(CORPUS, sample["image"])
    with open(path, "rb") as fh:
        blob = fh.read()
    media = OCR.media_type_of(sample["image"])
    ncols = sample.get("ncols") or OCR.NCOLS
    last = None
    for provider, host in LH.iter_hosts():
        try:
            page, warns = OCR.read_page(blob, media, host, ncols=ncols, model=model)
            return [r["cells"] for r in page["rows"]], warns, provider
        except Exception as exc:
            last = "%s: %s" % (provider, exc)
    raise RuntimeError("모든 공급자가 실패했다 — %s" % last)


def score(sample, pred_rows, notes):
    ncols = sample.get("ncols") or 20
    gold_rows = sample["gold"]

    # 정답 격자가 일부만 있을 수 있다(초안). CER은 겹치는 행끼리만 견준다 —
    # 예측 전체와 견주면 분모가 작아 CER이 1을 넘고 수치가 뜻을 잃는다.
    n = len(gold_rows)
    gold_text = rows_to_text(gold_rows, ncols)
    pred_head = rows_to_text(pred_rows[:n], ncols)
    # 침묵률은 지면 전체에서 본다. 학생 오류는 아래쪽 행에도 있다.
    pred_all = rows_to_text(pred_rows, ncols)

    align, cells, misses = cell_alignment(gold_rows, pred_rows, ncols)
    sil, lost = silence_rate(sample.get("keep"), pred_all)
    viol, viol_rows = row_length_violation(notes, len(pred_rows))
    return {
        "id": sample["id"],
        "침묵률": sil,
        "칸정렬": align,
        "CER": cer(gold_text, pred_head),
        "CER_무공백": cer(gold_text.replace(" ", "").replace("\n", ""),
                          pred_head.replace(" ", "").replace("\n", "")),
        "행길이위반률": viol,
        "칸수": cells,
        "_lost": lost, "_misses": misses, "_viol": viol_rows,
    }


def fmt(v):
    return "  —  " if v is None else "%.3f" % v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="한 편만 측정")
    ap.add_argument("--model", help="OCR 모델 지정")
    ap.add_argument("--offline", help="저장된 예측 json으로 재채점(호출 없음)")
    ap.add_argument("--save-pred", help="예측을 이 디렉터리에 남긴다")
    args = ap.parse_args()

    samples = []
    for name in sorted(os.listdir(CORPUS)) if os.path.isdir(CORPUS) else []:
        if not name.endswith(".json") or name.startswith("_"):
            continue
        with open(os.path.join(CORPUS, name), encoding="utf-8") as fh:
            s = json.load(fh)
        if args.id and s.get("id") != args.id:
            continue
        samples.append(s)

    if not samples:
        print("tests/corpus/ocr/ 에 표본이 없다. 이미지와 정답 격자를 먼저 넣는다.")
        return 1

    offline = None
    if args.offline:
        with open(args.offline, encoding="utf-8") as fh:
            offline = json.load(fh)

    rows_out = []
    for s in samples:
        if offline is not None:
            rec = offline.get(s["id"]) or {}
            pred_rows, notes, provider = rec.get("rows", []), rec.get("notes", []), "offline"
        else:
            pred_rows, notes, provider = predict(s, model=args.model)
            if args.save_pred:
                os.makedirs(args.save_pred, exist_ok=True)
                dst = os.path.join(args.save_pred, "pred.json")
                cur = {}
                if os.path.isfile(dst):
                    with open(dst, encoding="utf-8") as fh:
                        cur = json.load(fh)
                cur[s["id"]] = {"rows": pred_rows, "notes": notes, "provider": provider}
                with open(dst, "w", encoding="utf-8") as fh:
                    json.dump(cur, fh, ensure_ascii=False, indent=2)
        rows_out.append((score(s, pred_rows, notes), provider))

    print("\n표본 %d편   공급자 %s" % (len(rows_out), rows_out[0][1]))
    print("정답 격자가 초안인 표본은 수치가 잠정이다(confidence: draft)\n")
    print("%-22s %7s %7s %7s %9s %9s" %
          ("id", "침묵률", "칸정렬", "CER", "CER無공백", "행길이위반"))
    print("-" * 68)
    for r, _p in rows_out:
        print("%-22s %7s %7s %7s %9s %9s" %
              (r["id"], fmt(r["침묵률"]), fmt(r["칸정렬"]), fmt(r["CER"]),
               fmt(r["CER_무공백"]), fmt(r["행길이위반률"])))

    for r, _p in rows_out:
        if r["_lost"]:
            print("\n[%s] OCR이 고쳐 버린 학생 오류 %d건 — 침묵률 손실"
                  % (r["id"], len(r["_lost"])))
            for k in r["_lost"]:
                print("  %s" % k)
        if r["_viol"]:
            print("\n[%s] 행 길이 위반 %d건" % (r["id"], len(r["_viol"])))
            for n in r["_viol"][:10]:
                print("  %s" % n)
        if r["_misses"]:
            print("\n[%s] 칸 불일치 (앞 %d건) — (행,칸) 정답 -> 예측"
                  % (r["id"], len(r["_misses"])))
            for row, col, g, p in r["_misses"][:20]:
                print("  (%2d,%2d) %r -> %r" % (row, col, g, p))

    # 게이트는 손글씨 기준선을 세운 뒤 확정한다. 지금은 측정만 낸다.
    print("\n※ 게이트 수치는 기준선 수립 후 확정. 이 실행은 측정이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
