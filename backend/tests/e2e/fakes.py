"""종단 간 시나리오용 가짜 LLM. 프롬프트의 system 문구로 단계를 알아보고 요청 문장의 키워드로 응답한다 (호출 순서에 의존하지 않음).

실제 GPT-4o가 아니다. 단계 연결(① 규격화 ... ⑤ 렌더)과 모듈 재사용 경로를 키·네트워크 없이 확인하는 용도다.
"""
import json

from jejuagent.geo.climate import seed_module
from jejuagent.llm import FakeLLM


def COL(n, d="float", u=""):
    return {"name": n, "dtype": d, "unit": u, "min": None, "max": None}


def _plan(user: str) -> dict:
    off = "주식" in user
    crop = "감귤" if "감귤" in user else "월동무" if "월동무" in user else None
    point = crop is not None and ("어때" in user or "여기" in user)
    subs = ["이 지점의 기온 조건은?", "최근 시세는?"] if crop == "월동무" else ["이 지점의 기온 조건은?"]
    return {"goal": user.split("\n")[0][:40], "sub_questions": subs,
            "needs": {"point_analysis": point, "time_series": "시세" in user, "spatial_comparison": False},
            "location": {"kind": "none", "text": "제주시" if "제주시" in user else None, "lat": None, "lon": None},
            "crop": crop, "period": None, "style": "unspecified", "missing": [],
            "clarify_question": "어느 위치를 분석할까요? 지도에서 위치를 클릭하고 다시 보내 주세요.",
            "profit_guarantee": False, "tags": []}


def _select(user: str) -> dict:
    if "주식" in user.split("[카탈로그]")[0]:   # 카탈로그에 맞는 데이터가 없는 요청
        return {"feasible": False, "selected": [], "excluded": [], "unanswerable": [], "needed_data": ["주식 시세 데이터"],
                "infeasible_reason": "요청에 쓸 수 있는 데이터가 없습니다."}
    plan = json.loads(user.split("[RequestPlan] ")[1].split("\n[카탈로그]")[0])
    sel = [{"dataset_id": "jeju_weather_daily", "reason": "지점 기후", "columns": []}]
    if plan.get("crop") == "월동무":
        sel.append({"dataset_id": "jdh_agri_daily_trade", "reason": "월동무 시세", "columns": []})
    if plan.get("crop") == "감귤":
        sel.append({"dataset_id": "seogwipo_citrus_production", "reason": "감귤 생산", "columns": []})
    return {"feasible": True, "selected": sel, "excluded": [], "unanswerable": [], "infeasible_reason": "", "needed_data": []}


def _tasks(user: str) -> dict:
    chosen = user.split("[Profile")[0]
    site = {"id": "site", "title": "지점 기후 추정", "description": "AWS 관측소 값을 고도 보정 보간으로 지점 기온 지표와 교차검증 오차를 낸다",
            "inputs": ["jeju_weather_daily", "site_point"],
            "outputs": [{"id": "site_markers", "kind": "geo", "description": "지점과 관측소 위치", "columns": [COL("lat"), COL("lon")]},
                        {"id": "site_indicators", "kind": "metrics", "description": "지점 기온 지표", "columns": []},
                        {"id": "cross_validation", "kind": "table", "description": "교차검증 오차", "columns": [COL("mae_daily_c")]},
                        {"id": "site_limitations", "kind": "table", "description": "한계 문구", "columns": [COL("text", "str")]}]}
    price = {"id": "price", "title": "품목별 가격 추세와 변동성", "description": "월동무 일별 도매가격의 추세와 변동성",
             "inputs": ["jdh_agri_daily_trade"],
             "outputs": [{"id": "variety_trend_stats", "kind": "table", "description": "품종별 추세 통계", "columns": [COL("variety", "str")]},
                         {"id": "variety_daily_price", "kind": "series", "description": "품종별 일별 가격",
                          "columns": [COL("date", "date"), COL("price")]}]}
    return {"tasks": [site] + ([price] if '"dataset_id": "jdh_agri_daily_trade"' in chosen else [])}


def _decide(user: str) -> dict:
    if "[작업] 지점 기후" in user:
        roles = seed_module().MANIFEST["input_roles"]
        return {"decision": "reuse", "module_id": "site_climate", "reason": "verified 모듈이 그대로 맞다",
                "input_binding": [{"module_input": "aws", "task_input": "jeju_weather_daily"},
                                  {"module_input": "site", "task_input": "site_point"}],
                "role_mapping": [{"input": i, "role": r, "column": r} for i, rs in roles.items() for r in rs]}
    return {"decision": "reuse", "module_id": "market-price-trend-volatility", "reason": "verified 모듈이 그대로 맞다",
            "input_binding": [{"module_input": "trade", "task_input": "jdh_agri_daily_trade"}],
            "role_mapping": [{"input": "trade", "role": "date", "column": "baseDate"},
                             {"input": "trade", "role": "variety", "column": "cultivar"},
                             {"input": "trade", "role": "price", "column": "averagePrice"}]}


def _report(user: str) -> dict:
    blocks = []
    if "site_markers" in user:
        blocks += [{"type": "map", "artifact_id": "site_markers", "title": "지점과 관측소"},
                   {"type": "table", "artifact_id": "site_indicators", "title": "지점 기온 지표"},
                   {"type": "table", "artifact_id": "cross_validation", "title": "교차검증"}]
    if "variety_daily_price" in user:
        blocks.append({"type": "chart", "artifact_id": "variety_daily_price", "x": "date", "y": ["price"],
                       "chart_type": "line", "title": "품종별 일별 가격"})
    full = [{"artifact_id": None, "x": None, "y": [], "chart_type": "line", "title": None, "steps": [], "text": None, **b}
            for b in blocks]
    return {"title": "지점 기후 분석", "summary": "선택한 지점의 기온을 관측소 값에서 추정했습니다.",
            "sections": [{"heading": "결과", "text": "지점 기온 지표와 교차검증 결과입니다.", "blocks": full}], "limits": []}


def respond(system: str, user: str) -> dict:
    if "요청 규격화 담당" in system:
        return _plan(user)
    if "데이터 선택 담당" in system:
        return _select(user)
    if "작업 계획자" in system:
        return _tasks(user)
    if "기존 모듈을 쓸지" in system:
        return _decide(user)
    if "보고서로 설계하는 담당" in system:
        return _report(user)
    raise AssertionError(f"예상하지 못한 LLM 호출 (코드 생성 포함): {system[:40]}")


def make_llm() -> FakeLLM:
    return FakeLLM([respond] * 100)
