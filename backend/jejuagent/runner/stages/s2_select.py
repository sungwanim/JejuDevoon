"""② 데이터 선택 (티켓 04).

입력: state.plan, ctx.data.catalog()
출력: state.selection = {feasible, selected[{dataset_id, reason, columns, role}], excluded[{dataset_id, reason_code, note, by}],
      unanswered[{what, why}], sub_questions[{question, status, why}], infeasible_reason, needed_data}.
답하지 못한 부분은 state.unanswered에 더한다(러너가 partial로 처리). 쓸 데이터가 없으면 infeasible + needed_data.
"""
from __future__ import annotations

import json

from ... import thoughts
from ..selection import apply_rules, reduce_candidates, selection_schema, summarize

SYSTEM = (
    "당신은 제주 공공데이터 분석 도우미의 데이터 선택 담당입니다. 요청(RequestPlan)에 필요한 데이터셋을 카탈로그에서 고르세요.\n"
    "- 카탈로그에 있는 id만 쓸 수 있습니다. 모든 후보를 selected 또는 excluded에 넣으세요.\n"
    "- selected: 쓸 이유와 필요한 컬럼 이름. excluded: 이유 코드(irrelevant, granularity_mismatch, out_of_region, "
    "out_of_period, missing_columns)와 메모.\n"
    "- 공간 단위·지역·기간이 요청과 맞는지 보세요. 지점 분석에 시도 단위 데이터는 보조로만 쓸 수 있습니다.\n"
    "- 지점(점) 분석에는 공간 단위가 관측소·격자인 기후 데이터를 고르세요. 작목 시세 질문이 함께 있으면 시세 데이터도 고릅니다.\n"
    "- 답할 수 없는 하위 질문은 unanswerable에 이유와 함께 적으세요.\n"
    "- reason, note, infeasible_reason 등 모든 설명 문장은 한국어로 쓰세요(영어 금지).\n"
    "- 쓸 데이터가 하나도 없으면 feasible=false, infeasible_reason과 필요한 데이터 안내(needed_data)를 쓰세요.\n"
    "- relation: 요청이 서로 다른 두 데이터(주제)의 관계·상관·영향을 묻는 것이면 asked=true. 그때 한 쪽이 다른 쪽에 영향을 주거나 같은 원인을 공유한다고 "
    "의미상 설명할 수 있는 경로가 있으면 plausible=true, 연결할 이유가 없는 조합(예: 주식 가격과 재배면적)이면 plausible=false와 이유 한 문장. "
    "통계적으로 우연히 상관이 나올 수 있다는 점은 근거로 쓰지 않습니다. 관계를 묻지 않았으면 asked=false, plausible=true."
)


def run(state, ctx):
    plan = state.plan or {}
    catalog = ctx.data.catalog()
    if not catalog:  # 데이터 레지스트리가 없는 실행(EmptyRegistry): 선택할 것이 없어 통과. shortcut: 실서비스는 항상 카탈로그가 있다.
        ctx.trace.add("decision", stage="s2_select", skipped="empty_catalog")
        return state
    candidates = reduce_candidates(plan, catalog)
    user = (f"[RequestPlan] {json.dumps({k: plan.get(k) for k in ('goal', 'sub_questions', 'needs', 'location', 'crop', 'period')}, ensure_ascii=False)}\n"
            f"[카탈로그] {json.dumps([summarize(e) for e in candidates], ensure_ascii=False)}")
    raw = ctx.llm.structured(SYSTEM, user, selection_schema([e["id"] for e in candidates]),
                             schema_name="selection", purpose="s2_select").data
    sel = apply_rules(plan, catalog, candidates, raw)
    state.selection = sel
    state.unanswered.extend(sel["unanswered"])
    rel = raw.get("relation") or {}
    sel["relation"] = rel
    if not sel["feasible"]:
        state.finish("infeasible", sel["infeasible_reason"])
        state.needed_data = sel["needed_data"]
    elif rel.get("asked") and rel.get("plausible") is False:   # 의미상 연결할 근거가 없는 조합은 분석하지 않는다
        state.finish("infeasible", rel.get("reason") or "요청한 두 데이터는 관계를 분석할 근거가 없는 조합입니다.")
        state.needed_data = ["각 데이터를 따로 분석하는 요청"]
    titles = {e["id"]: e.get("title") or e["id"] for e in catalog}
    for line in thoughts.after_select(sel, titles):
        thoughts.say(ctx, "s2_select", line)
    ctx.trace.add("decision", stage="s2_select", feasible=sel["feasible"], candidates=len(candidates),
                  selected=sel["selected"], excluded=sel["excluded"], sub_questions=sel["sub_questions"],
                  unanswered=sel["unanswered"], relation=rel)
    return state
