"""테스트용 가짜 LLM. 미리 정한 응답을 호출 순서대로 돌려주고 호출 기록을 보존한다."""
from __future__ import annotations

from typing import Any, Callable

from .base import CallInfo, LLMClient, LLMError, LLMResponse, prompt_hash


class FakeLLM(LLMClient):
    """responses 항목: dict(structured 응답), str(text 응답), Exception(raise), callable(system, user)->dict|str."""

    model = "fake"

    def __init__(self, responses: list[Any] | None = None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []   # {kind, system, user, schema_name, schema, purpose}

    def _next(self, kind: str, system: str, user: str) -> Any:
        if not self.responses:
            raise LLMError(f"FakeLLM: 준비된 응답이 없습니다 (호출 {len(self.calls)}번째, {kind})")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, Callable):
            item = item(system, user)
        return item

    def structured(self, system, user, schema, *, schema_name="result", purpose=""):
        self.calls.append(dict(kind="structured", system=system, user=user,
                               schema_name=schema_name, schema=schema, purpose=purpose))
        data = self._next("structured", system, user)
        if not isinstance(data, dict):
            raise LLMError("FakeLLM: structured 호출에 dict가 아닌 응답이 준비되어 있습니다")
        info = CallInfo("structured", self.model, prompt_hash(system, user, schema), purpose=purpose)
        return LLMResponse(info=info, data=data)

    def text(self, system, user, *, purpose=""):
        self.calls.append(dict(kind="text", system=system, user=user,
                               schema_name=None, schema=None, purpose=purpose))
        txt = self._next("text", system, user)
        if not isinstance(txt, str):
            raise LLMError("FakeLLM: text 호출에 str이 아닌 응답이 준비되어 있습니다")
        info = CallInfo("text", self.model, prompt_hash(system, user), purpose=purpose)
        return LLMResponse(info=info, text=txt)
