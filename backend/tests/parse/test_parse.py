"""티켓 02: 요청 규격화. 가짜 LLM만 쓴다."""
import pytest

from jejuagent.llm import FakeLLM
from jejuagent.runner import run_agent
from jejuagent.runner.request_plan import out_of_range


def plan(**kw):
    p = {"goal": "g", "sub_questions": ["q1", "q2"],
         "needs": {"point_analysis": False, "time_series": False, "spatial_comparison": False},
         "location": {"kind": "none", "text": None, "lat": None, "lon": None},
         "crop": "감귤", "period": None, "style": "unspecified", "missing": [], "clarify_question": None,
         "profit_guarantee": False, "tags": []}
    for k, v in kw.items():
        p[k] = {**p[k], **v} if isinstance(v, dict) else v
    return p


def go(req, responses, tmp_path, **kw):
    fake = FakeLLM(responses)
    return run_agent(req, llm=fake, runs_dir=tmp_path, **kw), fake


def test_missing_location_clarify_then_continue(tmp_path):
    q = "어느 위치인가요?"
    res, _ = go("감귤 재배 적합도", [plan(needs={"point_analysis": True}, missing=["위치"], clarify_question=q)], tmp_path)
    assert res.status == "clarify" and res.state.reason == q
    assert res.state.plan["output_format"] == "map"
    prev = {"plan": res.state.plan, "request": "감귤 재배 적합도"}
    # 답변: 클릭 좌표와 함께. 이전 계획이 프롬프트에 합쳐진다
    res2, fake = go("여기요", [plan(needs={"point_analysis": True})], tmp_path, prev=prev,
                    click={"lat": 33.4, "lon": 126.5})
    assert res2.status == "answered"
    assert res2.state.plan["location"]["lat"] == 33.4 and res2.state.plan["missing"] == []
    assert "감귤 재배 적합도" in fake.calls[0]["user"] and "[이전 RequestPlan]" in fake.calls[0]["user"]


def test_point_analysis_without_coords_forces_clarify_even_if_llm_forgets(tmp_path):
    res, _ = go("x", [plan(needs={"point_analysis": True})], tmp_path)
    assert res.status == "clarify" and "위치" in res.state.plan["missing"]


def test_profit_guarantee_is_reframed_not_infeasible(tmp_path):
    res, _ = go("월동무로 돈 벌 수 있게 보장해줘", [plan(profit_guarantee=True)], tmp_path)
    assert res.status == "answered"
    assert "보장할 수 없" in res.state.plan["notice"]


@pytest.mark.parametrize("needs,style,fmt", [
    ({"point_analysis": True}, "easy", "map"),
    ({"spatial_comparison": True}, "unspecified", "map"),
    ({"time_series": True}, "easy", "visual"),
    ({"time_series": True}, "report", "report"),
    ({}, "unspecified", "report"),
])
def test_output_format_rule(tmp_path, needs, style, fmt):
    res, _ = go("x", [plan(needs=needs, style=style)], tmp_path, click={"lat": 33.4, "lon": 126.5})
    assert res.state.plan["output_format"] == fmt


def test_click_outside_jeju(tmp_path):
    res, _ = go("x", [plan(needs={"point_analysis": True})], tmp_path, click={"lat": 35.0, "lon": 129.0})
    assert res.status == "infeasible" and "범위 밖" in res.message
    assert out_of_range(33.4, 126.5) is None


def test_location_is_not_asked_when_not_a_point_analysis(tmp_path):
    res, _ = go("제주공항 소음이 어떻게 변했어?", [plan(needs={"time_series": True}, missing=["위치"], clarify_question="어느 위치인가요?")], tmp_path)
    assert res.status == "answered" and res.state.plan["missing"] == []
