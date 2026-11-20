"""사용자에게 보여 줄 생각 과정: 문장 만들기(순수 함수)와 실행 중 노출(trace 이벤트, 상태 API)."""
import time

from fastapi.testclient import TestClient

from jejuagent import thoughts as th
from jejuagent.api.app import create_app
from jejuagent.llm import FakeLLM
from jejuagent.runner import run_agent


def test_parse_and_select_sentences_explain_decisions():
    p = th.after_parse({"goal": "월동무 재배 적합성", "needs": {"point_analysis": True, "time_series": True}, "output_format": "map",
                        "missing": [], "profit_guarantee": True})
    assert "월동무 재배 적합성" in p[0] and any("선택한 지점의 기후" in x and "시간에 따른 변화" in x for x in p)
    assert any("지도" in x for x in p) and any("수익 보장" in x for x in p)
    sel = {"selected": [{"dataset_id": "a", "reason": "시세"}], "feasible": True,
           "excluded": [{"dataset_id": "b", "reason_code": "out_of_region"}, {"dataset_id": "c", "reason_code": "irrelevant"}],
           "relation": {"asked": True, "plausible": False, "reason": "연결 근거 없음"}}
    s = "\n".join(th.after_select(sel, {"a": "가격 통계", "b": "감귤 생산", "c": "소음"}))
    assert "가격 통계 (시세)" in s and "감귤 생산 - 요청 지역의 자료가 없음" in s and "소음" not in s   # irrelevant는 나열하지 않는다
    assert "근거가 없어서 멈춰요 (연결 근거 없음)" in s


def test_module_and_attempt_sentences():
    assert "재사용" in th.module_decision("t", "reuse", "m1", "") and "고쳐서" in th.module_decision("t", "adapt", "m1", "")
    assert "새 분석 코드" in th.module_decision("t", "new", None, "")
    assert "통과" in th.attempt("t", 1, True, "mock", None, "")
    assert "한 번 고쳐서" in th.attempt("t", 1, False, "mock", "code_bug", "x")
    assert "실패로 처리" in th.attempt("t", 2, False, "real", "code_bug", "x") and "실패로 처리" in th.attempt("t", 1, False, "real", "data_problem", "x")


def test_run_emits_thoughts_in_stage_order(tmp_path):
    res = run_agent("제주 월동무 가격 알려줘", llm=FakeLLM([{}]), runs_dir=tmp_path)
    ts = [e for e in res.events if e["type"] == "thought"]
    assert ts and ts[0]["stage"] == "s1_parse" and "요청을 이렇게 이해했어요" in ts[0]["text"]


def test_status_api_returns_thoughts_while_and_after_running(tmp_path):
    c = TestClient(create_app(lambda: FakeLLM([{}]), runs_dir=tmp_path))
    rid = c.post("/api/runs", json={"request": "제주 월동무 가격 알려줘"}).json()["run_id"]
    for _ in range(100):
        st = c.get(f"/api/runs/{rid}").json()
        if not st["running"]:
            break
        time.sleep(0.05)
    assert st["thoughts"] and {"stage", "text", "t"} <= st["thoughts"][0].keys()
