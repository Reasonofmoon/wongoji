# -*- coding: utf-8 -*-
"""Gemini function-calling adapter for chumsak_app.llm_layer."""
import json
import os
import urllib.error
import urllib.request

DEFAULT_MODEL = "gemini-3.7-flash"
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "%s:generateContent?key=%s")


def _sanitize_schema(node):
    """Gemini function parameters accept a JSON-schema subset."""
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in ("maxItems", "minItems", "additionalProperties", "$schema"):
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _sanitize_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _sanitize_schema(v)
        else:
            out[k] = v
    return out


def _tools(tools):
    decls = []
    for t in tools or []:
        schema = t.get("input_schema") or t.get("parameters") or {"type": "object"}
        decls.append({
            "name": t["name"],
            "description": t.get("description") or "",
            "parameters": _sanitize_schema(schema),
        })
    return [{"functionDeclarations": decls}] if decls else []


def _forced_name(tool_choice):
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "tool":
        return tool_choice.get("name")
    return None


def _parts(req):
    """이미지가 있으면 inline_data 파트를 먼저 넣는다. 원고지 OCR이 이 경로를 쓴다."""
    parts = []
    for img in req.get("images") or []:
        parts.append({"inline_data": {"mime_type": img.get("media_type") or "image/jpeg",
                                      "data": img["data"]}})
    for m in req.get("messages") or []:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str) and content:
            parts.append({"text": content})
    return parts or [{"text": ""}]


class Host:
    def __init__(self, model=None, api_key=None):
        self._model = model or os.environ.get("CHUMSAK_MODEL", DEFAULT_MODEL)
        self._key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not self._key:
            raise RuntimeError("GEMINI_API_KEY is missing")

    def reasoning_model(self):
        return self._model

    def llm(self, req):
        name = _forced_name(req.get("tool_choice"))
        body = {
            "systemInstruction": {"parts": [{"text": req.get("system") or ""}]},
            "contents": [{"role": "user", "parts": _parts(req)}],
            "generationConfig": {
                "maxOutputTokens": int(req.get("max_tokens") or 3000),
                "temperature": 0.2,
            },
        }
        tools = _tools(req.get("tools"))
        if tools:
            body["tools"] = tools
            cfg = {"mode": "ANY"}
            if name:
                cfg["allowedFunctionNames"] = [name]
            body["toolConfig"] = {"functionCallingConfig": cfg}

        url = ENDPOINT % (self._model, self._key)
        data = json.dumps(body).encode("utf-8")
        http_req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(http_req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError("Gemini HTTP %s: %s" % (exc.code, err[:400])) from exc

        tool_use = None
        texts = []
        for cand in payload.get("candidates") or []:
            parts = ((cand.get("content") or {}).get("parts")) or []
            for part in parts:
                fc = part.get("functionCall")
                if fc:
                    args = fc.get("args") or {}
                    if isinstance(args, str):
                        args = json.loads(args)
                    tool_use = {"name": fc.get("name"), "input": args}
                if part.get("text"):
                    texts.append(part["text"])
        return {"text": "".join(texts), "tool_use": tool_use,
                "model": self._model, "raw": payload}
