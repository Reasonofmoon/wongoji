# -*- coding: utf-8 -*-
"""경로·상한·환경. 서버 조각들이 같은 값을 보게 하는 단일 출처다.

Vercel에서는 쓰기 가능한 곳이 /tmp뿐이라 데이터 뿌리가 옮겨 간다. 이 분기를 여러
파일에 흩어 놓으면 한 곳만 고치고 나머지를 잊는다.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ON_VERCEL = bool(os.environ.get("VERCEL"))
DATA_ROOT = "/tmp/wongoji" if ON_VERCEL else HERE
if ON_VERCEL:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    os.environ.setdefault("HOME", "/tmp")
OUT = os.path.join(DATA_ROOT, "out")
SESS_DIR = os.path.join(DATA_ROOT, "data", "sessions")
OCR_DIR = os.path.join(DATA_ROOT, "data", "ocr")
WEB_DIR = os.path.join(HERE, "web")
INDEX_PATH = os.path.join(SESS_DIR, "_index.json")
SAMPLES_PATH = os.path.join(HERE, "samples.json")
os.makedirs(OUT, exist_ok=True)
os.makedirs(SESS_DIR, exist_ok=True)
os.makedirs(OCR_DIR, exist_ok=True)

MAX_TEXT = 4000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_PAGES = 12

DEMO_TEXT = ("어제 나는 친구와같이 놀이 터에서 놀았다. 그런데 갑자기 비 왔다 "
             "그래서 우리는 집으로 뛰어갔다. 아주 정말 재미있었다")


def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_samples():
    """앱에 들어 있는 시험용 원고. 정답 span은 담지 않는다 — 본문과 요약만."""
    if not os.path.isfile(SAMPLES_PATH):
        return []
    try:
        with open(SAMPLES_PATH, encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("samples") or []
    except (ValueError, OSError):
        return []
