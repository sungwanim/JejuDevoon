"""① 요청 규격화. LLM이 RequestPlan(하위 질문 분해 포함)을 내고, 코드 규칙이 형식·되묻기·범위·도메인을 정한다.

입력: state.request, state.click, state.prev ({"plan": 이전 RequestPlan, "request": 이전 요청}, 되묻기 답변일 때)
출력: state.plan = RequestPlan dict + output_format("map"|"report"|"visual") (+ notice: 재구성 안내).
종료: infeasible(도메인 밖·범위 밖), clarify(질문 1개는 state.reason). clarify 때도 state.plan을 남긴다.
"""
from __future__ import annotations

import json

from ..request_plan import (PROFIT_NOTICE, REQUEST_PLAN_SCHEMA, apply_rules, clarify_question, normalize,
                            out_of_range)

SYSTEM = (
    "당신은 제주 농업·기후·시장 데이터 분석 도우미의 요청 규격화 담당입니다. 사용자 요청을 RequestPlan으로 바꾸세요.\n"
    "- goal: 요청을 한 문장으로. sub_questions: 요청을 답할 수 있는 하위 질문들로 직접 분해.\n"
    "- needs: 특정 지점 분석(point_analysis), 시계열(time_series), 지역 간 공간 비교(spatial_comparison) 필요 여부.\n"
    "- location: 클릭 좌표가 주어지면 그것을 쓰고, 없고 텍스트만 있으면 kind=region/point와 text, 좌표는 모르면 null.\n"
    "- style: 보고서 형태를 원하면 report, 쉬운 설명을 원하면 easy, 언급 없으면 unspecified.\n"
    "- missing: 답하려면 꼭 필요한데 요청에 없는 정보(예: 위치, 작목). 없으면 빈 목록. 있으면 clarify_question에 질문 1개.\n"
    "- in_domain: 제주 농업·기후·농산물 시장 데이터 분석이면 true, 아니면 false와 domain_reason(한국어 한 문장).\n"
    "- profit_guarantee: 수익·이익을 보장해 달라는 요청이면 true (이 경우에도 in_domain은 true로 둔다).\n"
    "- tags: 분류용 짧은 태그. 이전 계획이 주어지면 사용자의 새 답변을 합쳐 계획 전체를 다시 작성하세요."
)


def _user_prompt(state) -> str:
    parts = []
    if state.prev:
        parts.append(f"[이전 요청] {state.prev.get('request', '')}\n[이전 RequestPlan] "
                     f"{json.dumps(state.prev.get('plan'), ensure_ascii=False)}\n[사용자의 답변] {state.request}")
    else:
        parts.append(f"[요청] {state.request}")
    if state.click:
        parts.append(f"[클릭 좌표] lat={state.click['lat']}, lon={state.click['lon']}")
    return "\n".join(parts)


def run(state, ctx):
    prev_plan = (state.prev or {}).get("plan")
    raw = ctx.llm.structured(SYSTEM, _user_prompt(state), REQUEST_PLAN_SCHEMA, schema_name="request_plan",
                             purpose="s1_parse").data
    plan = apply_rules(normalize(raw, state.click, prev_plan))
    state.plan = plan
    loc = plan["location"]

    if not plan["in_domain"]:
        why = plan["domain_reason"] or "제주 농업·기후·시장 데이터 분석과 관련 없는 요청입니다."
        state.finish("infeasible", why)
        state.needed_data = ["제주 농업·기후·시장 관련 데이터 분석 요청만 처리할 수 있습니다."]
    elif loc.get("lat") is not None and (msg := out_of_range(loc["lat"], loc["lon"])):
        state.finish("infeasible", msg)
        state.needed_data = ["제주 본섬 안의 위치"]
    elif plan["missing"]:
        state.finish("clarify", clarify_question(plan))
    elif plan["profit_guarantee"]:
        plan["notice"] = PROFIT_NOTICE
        state.extra.setdefault("notices", []).append(PROFIT_NOTICE)

    ctx.trace.add("decision", stage="s1_parse", status=state.status, output_format=plan["output_format"],
                  missing=plan["missing"], in_domain=plan["in_domain"], profit_guarantee=plan["profit_guarantee"])
    return state
