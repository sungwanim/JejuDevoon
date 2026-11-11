"""RunContext: 단계가 쓰는 주입 객체(LLM, 데이터 레지스트리)와 실행 상한."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..llm.base import LLMClient, LLMResponse
from .datasource import DataSourceRegistry
from .trace import Trace


class LimitExceeded(Exception):
    def __init__(self, which: str):
        super().__init__(which)
        self.which = which  # "llm_calls" | "time"


@dataclass
class Limits:
    max_llm_calls: int = 25
    max_seconds: float = 300.0


class LimitedLLM:
    """단계가 보는 LLM. 호출 수·시간 상한을 걸고 호출마다 trace에 기록한다. 단계는 항상 ctx.llm으로만 호출한다."""

    def __init__(self, inner: LLMClient, ctx: "RunContext"):
        self._inner, self._ctx = inner, ctx

    def _guard(self) -> None:
        c = self._ctx
        if c.disabled:
            raise LimitExceeded(c.disabled)
        if c.elapsed() > c.limits.max_seconds:
            raise LimitExceeded("time")
        if c.llm_calls >= c.limits.max_llm_calls:
            raise LimitExceeded("llm_calls")

    def _record(self, resp: LLMResponse) -> LLMResponse:
        self._ctx.llm_calls += 1
        resp.info.purpose = resp.info.purpose or self._ctx.stage
        self._ctx.trace.add("llm_call", stage=self._ctx.stage, **resp.info.to_dict())
        return resp

    def structured(self, system: str, user: str, schema: dict, *, schema_name: str = "result",
                   purpose: str = "") -> LLMResponse:
        self._guard()
        return self._record(self._inner.structured(system, user, schema, schema_name=schema_name, purpose=purpose))

    def text(self, system: str, user: str, *, purpose: str = "") -> LLMResponse:
        self._guard()
        return self._record(self._inner.text(system, user, purpose=purpose))


class RunContext:
    def __init__(self, llm: LLMClient, data: DataSourceRegistry, trace: Trace, limits: Limits | None = None,
                 modules=None):
        self.modules = modules                # ModuleStore | None. None이면 모듈 라이브러리를 쓰지 않는다(환경변수 JEJU_MODULE_STORE 제외)
        self.limits = limits or Limits()
        self.data = data
        self.trace = trace
        self.llm = LimitedLLM(llm, self)
        self.llm_calls = 0
        self.stage = ""
        self.disabled: str | None = None   # 상한에 걸린 뒤 LLM을 막는다 (렌더는 LLM 없이 가능한 만큼만)
        self._t0 = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._t0
