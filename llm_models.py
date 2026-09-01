# -*- coding: utf-8 -*-
"""BYOK 모델 카탈로그. 2026-08 공식 문서 기준 텍스트·도구 호출용만.

출처:
  xAI        https://docs.x.ai/developers/models
  Anthropic  https://platform.claude.com/docs/en/about-claude/models/overview
  Google     https://ai.google.dev/gemini-api/docs/models
  OpenAI     https://developers.openai.com/api/docs/models
"""
import os


# LLM 한 번 호출에 허용하는 초. **서버리스 함수 제한보다 짧아야 한다.**
# 길면 파이프라인이 규칙 계층으로 물러설 기회 없이 함수째 죽고(504), 교사는
# 첨삭본 대신 오류를 본다. 실측: 클라이언트 120초 > Vercel 60초라 항상 그랬다.
LLM_TIMEOUT = max(5, int(os.environ.get("CHUMSAK_LLM_TIMEOUT", "25")))

CATALOG = {
    "xai": {
        "label": "xAI Grok",
        "default": "grok-4.6",
        "key_env": "XAI_API_KEY",
        "key_hint": "xAI 콘솔 API 키, 또는 Grok CLI 로그인",
        "models": [
            {"id": "grok-4.6", "name": "Grok 4.6", "tag": "플래그십"},
            {"id": "grok-4.5", "name": "Grok 4.5", "tag": "이전 플래그십"},
            {"id": "grok-4.3", "name": "Grok 4.3", "tag": "가성비"},
            {"id": "grok-4-fast", "name": "Grok 4 Fast", "tag": "빠른 별칭"},
            {"id": "grok-4.20-0309-reasoning", "name": "Grok 4.20 Reasoning", "tag": "추론"},
            {"id": "grok-4.20-0309-non-reasoning", "name": "Grok 4.20", "tag": "비추론"},
            {"id": "grok-build-0.1", "name": "Grok Build 0.1", "tag": "코딩"},
        ],
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "default": "claude-sonnet-5",
        "key_env": "ANTHROPIC_API_KEY",
        "key_hint": "sk-ant-…",
        "models": [
            {"id": "claude-sonnet-5", "name": "Claude Sonnet 5", "tag": "권장"},
            {"id": "claude-opus-5", "name": "Claude Opus 5", "tag": "고지능"},
            {"id": "claude-fable-5", "name": "Claude Fable 5", "tag": "최상위"},
            {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "tag": "빠름"},
            {"id": "claude-opus-4-8", "name": "Claude Opus 4.8", "tag": "이전"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "tag": "이전"},
        ],
    },
    "gemini": {
        "label": "Google Gemini",
        "default": "gemini-3.7-flash",
        "key_env": "GEMINI_API_KEY",
        "key_hint": "AIza…  (Gemini API)",
        "models": [
            {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash", "tag": "최신"},
            {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash", "tag": "안정"},
            {"id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro", "tag": "프리뷰"},
            {"id": "gemini-3-flash-preview", "name": "Gemini 3 Flash", "tag": "프리뷰"},
            {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash", "tag": "이전"},
            {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash-Lite", "tag": "저가"},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tag": "2.5"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "tag": "2.5"},
        ],
    },
    "openai": {
        "label": "OpenAI",
        "default": "gpt-5.4",
        "key_env": "OPENAI_API_KEY",
        "key_hint": "sk-…  또는 sk-proj-…",
        "models": [
            {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol", "tag": "플래그십"},
            {"id": "gpt-5.6-terra", "name": "GPT-5.6 Terra", "tag": "균형"},
            {"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna", "tag": "저가"},
            {"id": "gpt-5.5", "name": "GPT-5.5", "tag": "고지능"},
            {"id": "gpt-5.4", "name": "GPT-5.4", "tag": "권장"},
            {"id": "gpt-5.4-mini", "name": "GPT-5.4 Mini", "tag": "미니"},
            {"id": "gpt-5.4-nano", "name": "GPT-5.4 nano", "tag": "나노"},
            {"id": "gpt-5.3-codex", "name": "GPT-5.3 Codex", "tag": "코딩"},
            {"id": "gpt-5.2", "name": "GPT-5.2", "tag": "이전"},
            {"id": "gpt-5-mini", "name": "GPT-5 Mini", "tag": "이전 미니"},
        ],
    },
}

PROVIDERS = tuple(CATALOG.keys())


def default_model(provider):
    pack = CATALOG.get(provider) or {}
    return pack.get("default")


def catalog_payload():
    return {
        "as_of": "2026-08-30",
        "providers": [
            {
                "id": pid,
                "label": pack["label"],
                "default": pack["default"],
                "key_env": pack["key_env"],
                "key_hint": pack["key_hint"],
                "models": pack["models"],
            }
            for pid, pack in CATALOG.items()
        ],
    }
