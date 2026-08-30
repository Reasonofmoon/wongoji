# -*- coding: utf-8 -*-
"""OpenAI Chat Completions adapter (tools) for chumsak_app.llm_layer."""
import json
import os
import urllib.error
import urllib.request

DEFAULT_MODEL = "gpt-5.4"


class Host:
    def __init__(self, model=None, api_key=None, base_url=None):
        self._model = model or os.environ.get("CHUMSAK_MODEL", DEFAULT_MODEL)
        self._key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base = (base_url or os.environ.get("OPENAI_BASE_URL")
                      or "https://api.openai.com/v1").rstrip("/")
        if not self._key:
            raise RuntimeError("OPENAI_API_KEY is missing")

    def reasoning_model(self):
        return self._model

    def llm(self, req):
        tools = []
        for t in req.get("tools") or []:
            tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description") or "",
                    "parameters": t.get("input_schema") or t.get("parameters") or {},
                },
            })
        choice = req.get("tool_choice") or {"type": "auto"}
        if isinstance(choice, dict) and choice.get("type") == "tool":
            choice = {"type": "function", "function": {"name": choice["name"]}}
        body = {
            "model": req.get("model") or self._model,
            "max_tokens": int(req.get("max_tokens") or 3000),
            "temperature": 0.2,
            "messages": ([{"role": "system", "content": req.get("system") or ""}]
                         + list(req.get("messages") or [])),
            "tools": tools,
            "tool_choice": choice,
        }
        http_req = urllib.request.Request(
            self._base + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self._key},
        )
        try:
            with urllib.request.urlopen(http_req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError("OpenAI HTTP %s: %s" % (exc.code, err[:400])) from exc
        msg = ((payload.get("choices") or [{}])[0].get("message")) or {}
        tool_use = None
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments") or "{}"
            if isinstance(args, str):
                args = json.loads(args or "{}")
            tool_use = {"name": fn.get("name"), "input": args}
            break
        return {"text": msg.get("content") or "", "tool_use": tool_use,
                "model": payload.get("model") or self._model}
