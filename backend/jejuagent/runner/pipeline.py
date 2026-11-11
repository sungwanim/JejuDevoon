"""파이프라인 등록부. 5단계 슬롯의 순서가 여기 있다. 후속 티켓은 이 파일이 아니라 자기 단계 파일만 바꾼다.

단계 인터페이스: `module.run(state: RunState, ctx: RunContext) -> RunState`
 - state를 제자리에서 갱신하고 돌려준다. 다음 단계로 넘길 값은 state 필드에 둔다.
 - 종료해야 하면 state.finish(status, reason) 를 호출한다. 러너가 그 단계 뒤에서 멈춘다.
 - LLM은 ctx.llm, 데이터는 ctx.data 로만 쓴다 (상한·trace 기록이 자동 적용된다).
 - 단계 안에서 일어난 중요한 결정은 ctx.trace.add("decision", stage=..., ...) 로 남긴다.
 - 예외를 그대로 던지면 러너가 failed로 처리하고 trace에 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from .stages import s1_parse, s2_select, s3_load, s4_analyze, s5_render


@dataclass(frozen=True)
class Stage:
    name: str
    module: ModuleType

    def run(self, state, ctx):
        return self.module.run(state, ctx)


STAGES: list[Stage] = [
    Stage("s1_parse", s1_parse),
    Stage("s2_select", s2_select),
    Stage("s3_load", s3_load),
    Stage("s4_analyze", s4_analyze),
    Stage("s5_render", s5_render),
]
RENDER_STAGE = "s5_render"  # 상한에 걸리면 이 단계로 건너뛰어 그때까지의 결과를 렌더한다
