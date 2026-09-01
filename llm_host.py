# -*- coding: utf-8 -*-
"""Pick an LLM host from settings.json or environment."""
import json
import os

import llm_models as LM

HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = "/tmp/wongoji/data" if os.environ.get("VERCEL") else os.path.join(HERE, "data")
SETTINGS = os.path.join(_DATA, "settings.json")

_CACHE = None


def load_settings():
    if not os.path.isfile(SETTINGS):
        return {}
    with open(SETTINGS, encoding="utf-8") as fh:
        return json.load(fh) or {}


def save_settings(data):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    cur = load_settings()
    cur.update({k: v for k, v in data.items() if v not in (None, "")})
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(cur, fh, ensure_ascii=False, indent=2)
    clear_cache()
    return cur


def clear_cache():
    global _CACHE
    _CACHE = None


def _hint(key):
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return "…" + key[-4:]


def grok_cli_token():
    """Use the signed-in Grok CLI session if no dedicated XAI_API_KEY exists."""
    path = os.path.expanduser("~/.grok/auth.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for rec in data.values():
            if isinstance(rec, dict) and rec.get("key"):
                return rec["key"]
    except Exception:
        return None
    return None


def detect_provider(settings=None):
    s = settings if settings is not None else load_settings()
    pinned = (s.get("provider") or os.environ.get("CHUMSAK_PROVIDER") or "").lower()
    if pinned in ("xai", "gemini", "anthropic", "openai"):
        return pinned
    key = s.get("api_key") or ""
    if key.startswith("AIza") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if key.startswith("sk-ant") or os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("XAI_API_KEY") or grok_cli_token():
        return "xai"
    if key.startswith("sk-") or os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if key:
        return "openai"
    return None


def _key_for(provider, settings):
    saved_provider = (settings.get("provider") or "").lower()
    if settings.get("api_key") and (not saved_provider or saved_provider == provider):
        return settings["api_key"]
    if provider == "gemini":
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY")
    if provider == "xai":
        return os.environ.get("XAI_API_KEY") or grok_cli_token()
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    return None


# 폴백 공급자는 빠른 모델로 간다. 주 공급자가 느려서 넘어온 상황이라
# 거기서도 플래그십을 쓰면 함수 제한에 두 번 걸린다.
FALLBACK_MODEL = {"xai": "grok-4-fast", "gemini": "gemini-3.6-flash",
                  "openai": "gpt-5.4-mini", "anthropic": "claude-haiku-4-5"}


def model_for(provider, settings=None, primary=True):
    """주 공급자의 모델 결정 순서: 설정 -> CHUMSAK_MODEL -> 카탈로그 기본값.

    get_host()와 iter_hosts()가 이 순서를 따로 구현하다 갈라졌다. iter_hosts()가
    환경변수를 빠뜨려, 배포 환경에 CHUMSAK_MODEL을 심어도 첨삭 경로에는 먹지
    않았다. CHUMSAK_NO_LLM 때와 같은 갈라짐이다. 결정은 한 곳에서 한다.
    """
    if not primary:
        return FALLBACK_MODEL.get(provider) or LM.default_model(provider)
    settings = settings if settings is not None else {}
    return (settings.get("model") or os.environ.get("CHUMSAK_MODEL")
            or LM.default_model(provider))


def make_host(provider=None, api_key=None, model=None):
    provider = (provider or detect_provider() or "").lower()
    if provider == "gemini":
        from llm_gemini import Host
        return Host(model=model, api_key=api_key), provider
    if provider == "anthropic":
        from llm_anthropic import Host
        return Host(model=model, api_key=api_key), provider
    if provider == "xai":
        from llm_openai import Host
        return Host(model=model or model_for("xai"),
                    api_key=api_key,
                    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.x.ai/v1")), provider
    if provider == "openai":
        from llm_openai import Host
        return Host(model=model, api_key=api_key), provider
    return None, None


def iter_hosts():
    """Primary provider first, then any other provider that still has a key.

    CHUMSAK_NO_LLM이 서면 아무것도 내지 않는다. get_host()만 이 변수를 보고 있어서
    run_pipeline과 OCR 라우터가 규칙만 돌라는 지시를 무시하고 유료 호출을 내보냈다.
    끄는 스위치는 한 곳에서 걸려야 한다.
    """
    if os.environ.get("CHUMSAK_NO_LLM"):
        return
    settings = load_settings()
    primary = detect_provider(settings)
    order = []
    if primary:
        order.append(primary)
    for p in ("xai", "anthropic", "openai", "gemini"):
        if p not in order:
            order.append(p)
    seen_keys = set()
    for provider in order:
        key = _key_for(provider, settings)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        model = model_for(provider, settings, primary=(provider == primary))
        try:
            host, _p = make_host(provider, api_key=key, model=model)
        except Exception:
            continue
        if host is not None:
            yield provider, host


def get_host():
    global _CACHE
    if os.environ.get("CHUMSAK_NO_LLM"):
        return None
    if _CACHE is not None:
        return _CACHE or None
    settings = load_settings()
    provider = detect_provider(settings)
    if not provider:
        _CACHE = False
        return None
    key = _key_for(provider, settings)
    model = model_for(provider, settings)
    try:
        host, _p = make_host(provider, api_key=key, model=model)
    except Exception:
        _CACHE = False
        return None
    _CACHE = host
    return host


def status():
    settings = load_settings()
    provider = detect_provider(settings)
    host = get_host()
    key = _key_for(provider, settings) if provider else None
    model = None
    if host is not None:
        model = host.reasoning_model()
    return {
        "llm": host is not None,
        "provider": provider,
        "model": model,
        "key_hint": _hint(key),
        "catalog": LM.catalog_payload(),
    }
