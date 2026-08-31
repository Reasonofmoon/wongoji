# -*- coding: utf-8 -*-
"""세션과 인식 결과를 디스크에 둔다.

메모리 dict만 두면 재시작과 동시 사용에 진다. 업로드한 사진은 여기 남기지 않는다 —
학생 손글씨는 개인정보이고, 남는 것은 칸 격자뿐이다.
"""
import json
import os

from server_config import INDEX_PATH, OCR_DIR, SESS_DIR


def _session_path(sid):
    return os.path.join(SESS_DIR, "%s.json" % sid)


def save_session(sid, res):
    payload = {
        "svg": res["svg"],
        "data": res["data"],
        "gate": res["gate"],
        "counts": res["counts"],
        "spec": res.get("spec") or {},
    }
    with open(_session_path(sid), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    latest = {"latest": sid}
    with open(INDEX_PATH, "w", encoding="utf-8") as fh:
        json.dump(latest, fh)


def load_session(sid):
    path = _session_path(sid)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def latest_session_id():
    if os.path.isfile(INDEX_PATH):
        with open(INDEX_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("latest")
    names = [n[:-5] for n in os.listdir(SESS_DIR) if n.endswith(".json") and n != "_index.json"]
    return sorted(names)[-1] if names else None


def session_count():
    return sum(1 for n in os.listdir(SESS_DIR)
               if n.endswith(".json") and n != "_index.json")


def ocr_path(oid):
    return os.path.join(OCR_DIR, "%s.json" % oid)


def save_ocr(rec):
    with open(ocr_path(rec["id"]), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False)
    return rec


def load_ocr(oid):
    """이미지는 저장하지 않는다. 칸 격자만 남는다."""
    if not oid or not str(oid).isalnum():
        return None
    path = ocr_path(oid)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
