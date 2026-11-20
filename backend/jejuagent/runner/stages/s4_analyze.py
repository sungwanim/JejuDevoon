"""④ 분석 (티켓 06).

입력: state.plan, state.selection, state.data, state.profiles
출력: state.tasks(작업별 시도·실패 분류·코드), state.artifacts(id -> analysis.Artifact), 실패한 작업은 state.unanswered

흐름: LLM이 순서 있는 작업 목록을 낸다(재계획 없음) -> 작업마다 analysis.tasks.run_task.
 - 작업이 끝내 실패하면 표시하고 다음 작업으로 간다 (실패한 작업은 unanswered에 {"what","why","classification"}로 남는다).
 - 모든 작업 실패(또는 작업 목록이 비었음) -> state.finish("failed", ...). 일부 실패는 종료 상태를 정하지 않는다:
   러너 기본값/렌더 단계(08)가 unanswered를 보고 partial로 만든다 (finish를 부르면 렌더가 건너뛰어지므로).
 - 상한(LimitExceeded)은 그대로 올려 러너가 그때까지의 결과로 렌더하게 한다. 남은 작업은 status="not_run".
"""
from ...analysis.tasks import STAGE, plan_tasks, run_task
from ... import thoughts
from ..context import LimitExceeded


def run(state, ctx):
    if not state.data:  # 선택된 데이터가 없으면 분석할 것이 없다 (불가 판정은 ②의 몫). 선택했는데 전부 로드 실패면 failed
        if state.load_failures:
            state.finish("failed", "선택한 데이터를 모두 불러오지 못했습니다.")
        return state
    state.tasks = tasks = plan_tasks(state, ctx)
    ctx.trace.add("decision", stage=STAGE, tasks=[{k: t[k] for k in ("id", "title", "inputs")} for t in tasks])
    if tasks:
        thoughts.say(ctx, STAGE, thoughts.plan_tasks(tasks))
    try:
        for t in tasks:
            run_task(t, state, ctx)
            thoughts.say(ctx, STAGE, thoughts.task_done(t))
            if t["status"] == "failed":
                state.unanswered.append(t["failure"])
                ctx.trace.add("decision", stage=STAGE, task_id=t["id"], task_failed=t["failure"])
    except LimitExceeded:
        for t in tasks:
            if t["status"] == "pending":
                t["status"] = "not_run"
                state.unanswered.append({"what": f"{t['title']}: {t['description']}", "why": "실행 상한에 걸려 실행하지 못함"})
        raise
    if not any(t["status"] == "ok" for t in tasks):
        why = "; ".join(t["failure"]["why"] for t in tasks if t["failure"]) or "작업 목록이 비어 있다"
        state.finish("failed", f"모든 분석 작업이 실패했습니다: {why}")
    return state
