"""사용자에게 보여 줄 '생각 과정' 문장. 각 단계가 이미 내린 결정(요청 규격화, 데이터 선택, 모듈 결정 등)을 쉬운 한국어로 옮긴다.
LLM의 숨은 추론이 아니라 실행 기록에 남는 결정과 그 이유다. 화면은 trace의 'thought' 이벤트를 순서대로 보여 준다."""
from __future__ import annotations

REASON_KO = {"irrelevant": "질문과 관련이 적음", "granularity_mismatch": "공간 단위가 맞지 않음", "out_of_region": "요청 지역의 자료가 없음",
             "out_of_period": "요청 기간과 겹치지 않음", "missing_columns": "필요한 컬럼이 없음"}
FORMAT_KO = {"map": "지도", "report": "보고서", "visual": "그림"}
PHASE_KO = {"static": "코드 검사", "mock": "모의 데이터", "real": "실제 데이터", "cache": "저장된 결과"}
MAX_LISTED = 4


def say(ctx, stage: str, text: str) -> None:
    ctx.trace.add("thought", stage=stage, text=text)


def after_parse(plan: dict) -> list[str]:
    out = [f"요청을 이렇게 이해했어요: {plan.get('goal') or '(목표 없음)'}"]
    needs = plan.get("needs") or {}
    parts = [n for k, n in (("point_analysis", "선택한 지점의 기후"), ("time_series", "시간에 따른 변화"), ("spatial_comparison", "지역 간 비교")) if needs.get(k)]
    if parts:
        out.append("필요한 분석: " + ", ".join(parts))
    fmt = FORMAT_KO.get(plan.get("output_format"), "")
    if fmt:
        out.append(f"결과는 {fmt} 형식으로 보여드릴게요" + (" (공간 정보가 필요해서 지도로 정했어요)" if plan.get("output_format") == "map" else ""))
    if plan.get("missing"):
        out.append("답하려면 " + ", ".join(plan["missing"]) + " 정보가 더 필요해서 먼저 여쭤볼게요")
    if plan.get("profit_guarantee"):
        out.append("수익 보장은 할 수 없어서, 참고할 수 있는 지표를 보여드리는 쪽으로 바꿀게요")
    return out


def after_select(sel: dict, titles: dict[str, str]) -> list[str]:
    t = lambda i: titles.get(i, i)
    out = []
    chosen = sel.get("selected") or []
    if chosen:
        out.append(f"사용할 데이터 {len(chosen)}개를 골랐어요: " + "; ".join(f"{t(s['dataset_id'])} ({s.get('reason') or '관련 있음'})" for s in chosen[:MAX_LISTED]))
    cut = [x for x in sel.get("excluded") or [] if x.get("reason_code") != "irrelevant"]
    if cut:
        out.append("제외한 데이터: " + "; ".join(f"{t(x['dataset_id'])} - {REASON_KO.get(x['reason_code'], x['reason_code'])}" for x in cut[:MAX_LISTED]))
    rel = sel.get("relation") or {}
    if rel.get("asked"):
        out.append("서로 다른 데이터의 관계를 묻는 요청이라 연결할 근거가 있는지 따져 봤어요: " +
                   ("의미상 설명할 수 있어서 진행해요" if rel.get("plausible", True) else f"근거가 없어서 멈춰요 ({rel.get('reason') or '연결 경로 없음'})"))
    if not sel.get("feasible", True):
        out.append("쓸 수 있는 데이터가 없어요: " + (sel.get("infeasible_reason") or "카탈로그에 맞는 데이터 없음"))
    return out


def after_load(data: dict, titles: dict[str, str], failures: list[dict]) -> list[str]:
    out = []
    shown = {k: v for k, v in data.items() if k != "site_point"}
    if shown:
        out.append("데이터를 불러왔어요: " + "; ".join(f"{titles.get(k, k)} {len(v):,}행" for k, v in list(shown.items())[:MAX_LISTED]))
    if "site_point" in data:
        z = float(data["site_point"]["elevation_m"].iloc[0])
        out.append(f"선택한 지점의 고도를 지형 자료(DEM)에서 읽었어요: {z:.0f}m")
    if failures:
        out.append("불러오지 못한 데이터는 빼고 진행해요: " + ", ".join(str(f.get("dataset_id")) for f in failures))
    return out


def plan_tasks(tasks: list[dict]) -> str:
    return f"분석을 {len(tasks)}개 작업으로 나눴어요: " + " / ".join(f"{i}) {t['title']}" for i, t in enumerate(tasks, 1))


def module_decision(title: str, kind: str, module_id: str | None, reason: str) -> str:
    why = f" - {reason}" if reason else ""
    if kind == "reuse":
        return f"'{title}': 이미 검증된 모듈 '{module_id}'이(가) 맞아서 그대로 재사용해요{why}"
    if kind == "adapt":
        return f"'{title}': 비슷한 모듈 '{module_id}'을(를) 이 데이터에 맞게 고쳐서 써요{why}"
    return f"'{title}': 맞는 모듈이 없어 데이터 구조만 보고 새 분석 코드를 만들어요{why}"


def attempt(title: str, n: int, ok: bool, phase: str, failure: str | None, message: str) -> str:
    if ok:
        return f"'{title}': 코드 검증을 통과했어요 ({PHASE_KO.get(phase, phase)}에서 확인)"
    nxt = "원인을 보고 한 번 고쳐서 다시 시도해요" if n == 1 and failure != "data_problem" else "더 시도하지 않고 이 작업은 실패로 처리해요"
    return f"'{title}': 코드 검증에서 문제가 있었어요 ({PHASE_KO.get(phase, phase)}, {failure or '오류'}): {message[:80]}. {nxt}"


def task_done(task: dict) -> str:
    if task.get("status") == "ok":
        return f"'{task['title']}' 작업 완료"
    why = (task.get("failure") or {}).get("why", "")
    return f"'{task['title']}' 작업 실패" + (f": {why[:80]}" if why else "")


def before_render(plan: dict) -> str:
    fmt = FORMAT_KO.get(plan.get("output_format"), "보고서")
    return f"결과 화면을 {fmt} 형식으로 만들어요. 계산 결과에 없는 숫자가 든 문장은 걸러내요"


def after_render(removed: int, fallback: bool) -> str | None:
    if fallback:
        return "AI 요약 없이 표와 숫자 중심으로 보여드려요"
    return f"근거 없는 숫자가 든 문장 {removed}개를 뺐어요" if removed else None
