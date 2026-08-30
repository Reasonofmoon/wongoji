# -*- coding: utf-8 -*-
"""chumsak_app.llm_layer가 기대하는 host 인터페이스를 Anthropic API로 구현한 어댑터.

주의: 이 파일은 참고 코드다. 이 저장소의 개발 환경에는 API 키가 없어 실행 검증되지 않았다.
필요한 것은 두 가지뿐이다.
    host.llm(request_dict) -> {"tool_use": {"name": ..., "input": {...}}}
    host.reasoning_model() -> str

사용:
    import server, llm_anthropic
    server.HOST = llm_anthropic.Host()      # ANTHROPIC_API_KEY 환경변수 필요
"""
import os

DEFAULT_MODEL = "claude-sonnet-4-5"


class Host:
    def __init__(self, model=None, api_key=None):
        import anthropic                      # pip install anthropic
        self._model = model or os.environ.get("CHUMSAK_MODEL", DEFAULT_MODEL)
        self._cli = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])

    def reasoning_model(self):
        return self._model

    def llm(self, req):
        """chumsak_app이 넘기는 요청 딕셔너리를 messages.create 호출로 옮긴다."""
        msg = self._cli.messages.create(
            model=req.get("model") or self._model,
            max_tokens=req.get("max_tokens", 3000),
            system=req.get("system", ""),
            tools=req.get("tools") or [],
            tool_choice=req.get("tool_choice") or {"type": "auto"},
            messages=req["messages"],
        )
        tool_use = None
        for blk in msg.content:
            if getattr(blk, "type", None) == "tool_use":
                tool_use = {"name": blk.name, "input": blk.input}
        text = "".join(getattr(b, "text", "") for b in msg.content)
        return {"text": text, "tool_use": tool_use, "model": msg.model,
                "stop_reason": msg.stop_reason}
