"""④ 분석 경계 테스트: Runner 경계(run_agent)에서 가짜 LLM이 코드 문자열을 돌려준다. 키·네트워크 불필요.

① 요청 규격화·② 데이터 선택은 다른 티켓이라 가짜 단계로 대신하고, ③ 로드와 ④ 분석은 진짜 단계를 쓴다.
"""
import types

from jejuagent.llm import FakeLLM
from jejuagent.runner import run_agent
from jejuagent.runner.datasource import SnapshotRegistry
from jejuagent.runner.pipeline import Stage
from jejuagent.runner.stages import s3_load, s4_analyze

DS = "jdh_agri_daily_trade"
MAP = [{"input": DS, "role": "date", "column": "baseDate"}, {"input": DS, "role": "variety", "column": "cultivar"},
       {"input": DS, "role": "price", "column": "averagePrice"}]
BAD_MAP = [{**m, "column": "price_krw"} if m["role"] == "price" else m for m in MAP]
COL = lambda n, d, u="": {"name": n, "dtype": d, "unit": u, "min": None, "max": None}  # noqa: E731
TREND_OUT = {"id": "radish_price_trend", "kind": "series", "description": "월동무 일별 가격과 7일 이동평균",
             "columns": [COL("date", "date"), {**COL("price", "float", "원/kg"), "min": 0, "max": 100000},
                         COL("ma7", "float", "원/kg")]}
T1 = {"id": "t1", "title": "월동무 가격 시계열", "description": "월동무 일별 평균 도매가격과 7일 이동평균", "inputs": [DS],
      "outputs": [TREND_OUT]}
T2 = {"id": "t2", "title": "추세 요약", "description": "최근 가격과 기간 변화율", "inputs": ["radish_price_trend"],
      "outputs": [{"id": "trend_summary", "kind": "metrics", "description": "최근 가격과 변화율", "columns": []}]}

GOOD = '''
import jejukit
import pandas as pd
MANIFEST = {"title": "품종 가격 시계열", "description": "품종 일별 가격과 이동평균", "tags": ["price"],
            "input_roles": {"jdh_agri_daily_trade": {"date": "date", "variety": "str", "price": "float"}},
            "params": {}, "outputs": ["radish_price_trend"]}
def run(inputs, params):
    df = inputs["jdh_agri_daily_trade"]
    df = df[df["variety"] == "월동무"]
    if df.empty:
        raise DataProblem("월동무 행이 없다")
    out = df.sort_values("date")[["date"]].copy()
    out["price"] = jejukit.to_numeric(df.sort_values("date")["price"])
    out["ma7"] = out["price"].rolling(7, min_periods=1).mean()
    return {"radish_price_trend": out.reset_index(drop=True)}
def check(outputs, inputs):
    o = outputs["radish_price_trend"]
    return [] if len(o) > 0 and o["price"].notna().all() else ["가격이 비었다"]
'''
SUMMARY = '''
MANIFEST = {"title": "추세 요약", "description": "최근 가격과 변화율", "tags": ["price"],
            "input_roles": {"radish_price_trend": {"date": "date", "price": "float"}},
            "params": {}, "outputs": ["trend_summary"]}
def run(inputs, params):
    df = inputs["radish_price_trend"].sort_values("date")
    first, last = float(df["price"].iloc[0]), float(df["price"].iloc[-1])
    return {"trend_summary": {"last_price": last, "change_pct": (last - first) / first * 100}}
def check(outputs, inputs):
    return [] if outputs["trend_summary"]["last_price"] > 0 else ["최근 가격이 0 이하"]
'''
SUMMARY_MAP = [{"input": "radish_price_trend", "role": "date", "column": "date"},
               {"input": "radish_price_trend", "role": "price", "column": "price"}]
# 작업마다 다른 코드가 나오도록 제목·이름만 바꾼 변형
BAD_CHECK = GOOD.replace('return [] if len(o) > 0 and o["price"].notna().all() else ["가격이 비었다"]',
                         'return ["항상 실패하는 검증"]')
CRASH = GOOD.replace('out["ma7"] = out["price"].rolling(7, min_periods=1).mean()', 'out["ma7"] = float("x")')
NODATA = GOOD.replace('df = df[df["variety"] == "월동무"]', 'df = df[df["variety"] == "없는품종"]')


def codes(code, mapping=MAP):
    return {"code": code, "role_mapping": mapping}


def go(tmp_path, responses, tasks=None, llm_calls=None):
    def setup(state, ctx):  # ①②를 대신한다
        state.plan = {"goal": "월동무 최근 가격 추세", "sub_questions": ["월동무 최근 가격은 어떻게 변했나"]}
        state.selection = {"selected": [{"dataset_id": DS, "reason": "가격 데이터", "columns": []}]}
        return state
    stages = [Stage("s1_parse", types.SimpleNamespace(run=setup)), Stage("s3_load", s3_load),
              Stage("s4_analyze", s4_analyze)]
    llm = FakeLLM([{"tasks": tasks or [T1]}, *responses])
    res = run_agent("월동무 최근 가격 추세 알려줘", llm=llm, data=SnapshotRegistry(), runs_dir=tmp_path, stages=stages)
    return res, llm


def attempts(res, i=0):
    return res.state.tasks[i]["attempts"]


def test_first_attempt_success_and_chained_task(tmp_path):
    res, llm = go(tmp_path, [codes(GOOD), codes(SUMMARY, SUMMARY_MAP)], tasks=[T1, T2])
    assert res.status == "answered"
    a = res.state.artifacts["radish_price_trend"]
    assert list(a.value.columns) == ["date", "price", "ma7"] and len(a.value) > 20
    assert a.source_ids == [DS] and a.role_mapping[DS]["price"] == "averagePrice" and a.module_title == "품종 가격 시계열"
    assert res.state.artifacts["trend_summary"].value["last_price"] > 0          # 앞 작업의 산출물을 입력으로 썼다
    assert [t["status"] for t in res.state.tasks] == ["ok", "ok"] and len(attempts(res)) == 1
    assert [c["purpose"] for c in llm.calls][:2] == ["s4_plan_tasks", "s4_codegen:t1"]
    # LLM에는 Profile·샘플만 간다: 원본 행 전체는 가지 않는다
    df = SnapshotRegistry().load(DS)
    user = llm.calls[1]["user"]
    assert "samples" in user and str(df["averagePrice"].iloc[100]) not in user and len(user) < 12000
    # trace 직렬화: 중간산출물은 요약으로 남는다
    assert "<Artifact shape=" in str(res.state.to_dict()["artifacts"]["radish_price_trend"])


def test_fail_then_fix_succeeds(tmp_path):
    res, llm = go(tmp_path, [codes(BAD_CHECK), codes(GOOD)])
    assert res.status == "answered"
    t = res.state.tasks[0]
    assert t["status"] == "ok" and [x["n"] for x in t["attempts"]] == [1, 2]
    assert t["attempts"][0]["failure"] == "validation_failed" and t["attempts"][0]["phase"] == "mock"
    assert "validation_failed" in llm.calls[2]["user"] and "항상 실패하는 검증" in llm.calls[2]["user"]
    assert t["attempts"][1]["ok"]


def test_column_mismatch_remaps_instead_of_rewriting_code(tmp_path):
    res, llm = go(tmp_path, [codes(GOOD, BAD_MAP), {"role_mapping": MAP}])
    assert res.status == "answered"
    t = res.state.tasks[0]
    assert t["attempts"][0]["failure"] == "column_role_mismatch" and t["attempts"][1]["kind"] == "remap"
    assert t["attempts"][0]["code_hash"] == t["attempts"][1]["code_hash"]
    assert "averagePrice" in llm.calls[2]["user"]          # 실제 컬럼 목록이 제공된다
    assert llm.calls[2]["schema_name"] == "analysis_remap"


def test_second_attempt_also_fails_then_next_task_runs(tmp_path):
    t1b = {**T1, "id": "t1b", "outputs": [{**TREND_OUT, "id": "o2"}]}
    res, llm = go(tmp_path, [codes(CRASH), codes(CRASH.replace('float("x")', 'float("y")')),
                             codes(GOOD.replace("radish_price_trend", "o2"))], tasks=[T1, t1b])
    assert res.state.tasks[0]["status"] == "failed" and len(attempts(res)) == 2
    f = res.state.tasks[0]["failure"]
    assert f["what"].startswith("월동무 가격 시계열") and f["why"] and f["classification"] == "format_error"
    assert res.state.unanswered == [f]
    assert res.state.tasks[1]["status"] == "ok" and "o2" in res.state.artifacts   # 실패 뒤 다음 작업으로 넘어갔다
    assert res.status == "partial"


def test_identical_second_attempt_is_not_run(tmp_path):
    same = CRASH.replace("\ndef run", "\n# 주석만 다르다\n\n\ndef run")
    res, llm = go(tmp_path, [codes(CRASH), codes(same)])
    t = res.state.tasks[0]
    assert t["status"] == "failed" and t["failure"]["classification"] == "identical_retry"
    assert t["attempts"][1]["identical_to_first"] and t["attempts"][1]["ok"] is False
    assert res.status == "failed" and len(llm.calls) == 3


def test_data_problem_fails_without_second_attempt(tmp_path):
    res, llm = go(tmp_path, [codes(NODATA)])
    t = res.state.tasks[0]
    assert t["status"] == "failed" and t["failure"]["classification"] == "data_problem" and len(t["attempts"]) == 1
    assert len(llm.calls) == 2                                 # 계획 + 1차 코드, 수정 호출 없음
    assert res.status == "failed" and "모든 분석 작업이 실패" in res.message   # 모든 작업 실패 -> failed
    assert any(e["type"] == "decision" and e.get("task_failed") for e in res.events)


def test_all_tasks_failed_is_failed_and_partial_otherwise(tmp_path):
    res, _ = go(tmp_path, [codes(NODATA), codes(NODATA)], tasks=[T1, {**T1, "id": "t2", "outputs": [{**TREND_OUT, "id": "o2"}]}])
    assert res.status == "failed" and [t["status"] for t in res.state.tasks] == ["failed", "failed"]
    res, _ = go(tmp_path, [codes(GOOD), codes(NODATA)], tasks=[T1, {**T1, "id": "t2", "outputs": [{**TREND_OUT, "id": "o2"}]}])
    assert res.status == "partial" and len(res.state.unanswered) == 1 and "radish_price_trend" in res.state.artifacts


def test_temperature_and_seed_fixed_in_adapter():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "jejuagent" / "llm" / "openai_client.py").read_text(encoding="utf-8")
    assert "temperature=0" in src and "seed=SEED" in src
