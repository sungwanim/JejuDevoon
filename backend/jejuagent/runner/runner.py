"""Agent Runner: 단일 진입점 run_agent(). 프레임워크 없는 상태 머신."""
from __future__ import annotations

import json
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..llm.base import LLMClient, LLMError
from .context import LimitExceeded, Limits, RunContext
from .datasource import DataSourceRegistry, EmptyRegistry
from .pipeline import RENDER_STAGE, STAGES, Stage
from .state import RunState
from .trace import Trace

DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[3] / "runs"


@dataclass
class RunResult:
    status: str
    message: str
    html: str | None
    state: RunState
    events: list[dict]      # trace 이벤트 (stage / transition / llm_call / decision / error)
    trace_path: Path | None


def run_agent(request: str, *, llm: LLMClient, data: DataSourceRegistry | None = None,
              click: dict | None = None, prev: dict | None = None,
              runs_dir: str | Path | None = DEFAULT_RUNS_DIR, limits: Limits | None = None,
              run_id: str | None = None, stages: list[Stage] | None = None,
              on_progress: Callable[[RunState, Trace], None] | None = None, modules=None) -> RunResult:
    """요청 문장(+클릭 좌표, 되묻기 이전 상태) -> 종료 상태·HTML·실행 기록. runs_dir=None이면 저장 안 함."""
    stages = stages or STAGES
    state = RunState(run_id=run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
                     request=request, click=click, prev=prev)
    trace = Trace(state.run_id, runs_dir)
    ctx = RunContext(llm, data or EmptyRegistry(), trace, limits, modules)
    trace.add("start", request=request, click=click, has_prev=prev is not None)

    def checkpoint():
        trace.save(state.to_dict(), state.html)
        if on_progress:
            on_progress(state, trace)

    checkpoint()
    i = 0
    while i < len(stages) and state.status is None:
        stage = stages[i]
        try:
            _run_stage(stage, state, ctx, trace)
        except LimitExceeded as e:
            trace.add("limit", which=e.which, stage=stage.name, llm_calls=ctx.llm_calls)
            state.limit_hit, ctx.disabled = e.which, e.which
            # 그때까지의 결과로 렌더 단계로 건너뛴다. 이미 렌더 중이었다면 그대로 끝낸다.
            nxt = next((k for k, s in enumerate(stages) if s.name == RENDER_STAGE), len(stages))
            i = nxt if nxt > i else len(stages)
            _transition(trace, stage.name, stages[i].name if i < len(stages) else "end", "limit")
            checkpoint()
            continue
        except Exception as e:  # 시스템 오류 -> failed
            trace.add("error", stage=stage.name, error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
            hint = str(e) if isinstance(e, LLMError) else "시스템 오류가 발생했습니다. 실행 기록(trace)을 확인해 주세요."
            state.finish("failed", f"{type(e).__name__}: {e}", hint)
            checkpoint()
            break
        i += 1
        _transition(trace, stage.name, stages[i].name if i < len(stages) and state.status is None else "end",
                    state.status or "next")
        checkpoint()

    if state.status is None:  # 단계들이 종료 상태를 정하지 않았을 때의 기본값
        partial = state.limit_hit or state.load_failures or state.unanswered
        state.finish("partial" if partial else "answered",
                     message="상한에 걸려 그때까지의 결과로 종료했습니다." if state.limit_hit else state.message)
    state.stage = "done"
    trace.add("end", status=state.status, llm_calls=ctx.llm_calls, seconds=round(ctx.elapsed(), 3))
    path = trace.save(state.to_dict(), state.html)
    if on_progress:
        on_progress(state, trace)
    return RunResult(state.status, state.message, state.html, state, trace.events, path)


def _run_stage(stage: Stage, state: RunState, ctx: RunContext, trace: Trace) -> None:
    if ctx.elapsed() > ctx.limits.max_seconds and not ctx.disabled:
        raise LimitExceeded("time")
    state.stage = ctx.stage = stage.name
    before = _snapshot(state)
    t0 = time.monotonic()
    ev = trace.add("stage", name=stage.name, status="running")
    try:
        stage.run(state, ctx)
    finally:
        ev.update(status="done", ms=int((time.monotonic() - t0) * 1000), changed=_changed(before, _snapshot(state)))


def _transition(trace: Trace, src: str, dst: str, why: str) -> None:
    trace.add("transition", **{"from": src, "to": dst, "why": why})


def _snapshot(state: RunState) -> dict:
    return {k: json.dumps(v, ensure_ascii=False, default=str) for k, v in state.to_dict().items() if k != "stage"}


def _changed(before: dict, after: dict) -> dict:
    """단계가 바꾼 필드의 새 값 (단계별 출력 기록)."""
    return {k: json.loads(v) for k, v in after.items() if before.get(k) != v}
