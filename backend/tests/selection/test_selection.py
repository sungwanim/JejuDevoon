"""티켓 04: 데이터 선택. 가짜 LLM만 쓴다."""
import pytest

from jejuagent.llm import FakeLLM
from jejuagent.runner.context import RunContext
from jejuagent.runner.datasource import DataSourceRegistry, SnapshotRegistry
from jejuagent.runner.selection import reduce_candidates
from jejuagent.runner.stages import s2_select
from jejuagent.runner.state import RunState
from jejuagent.runner.trace import Trace

CIT, TRADE = "seogwipo_citrus_production", "jdh_agri_daily_trade"


def plan(**kw):
    p = {"goal": "g", "sub_questions": ["생산 현황", "가격 추이"],
         "needs": {"point_analysis": False, "time_series": False, "spatial_comparison": False},
         "location": {"kind": "region", "text": None, "lat": None, "lon": None},
         "crop": "감귤", "period": None}
    for k, v in kw.items():
        p[k] = {**p[k], **v} if isinstance(v, dict) else v
    return p


def llm_out(selected=(), excluded=(), unanswerable=(), feasible=True, why="", needed=()):
    return {"feasible": feasible,
            "selected": [{"dataset_id": i, "reason": "r", "columns": c} for i, c in selected],
            "excluded": [{"dataset_id": i, "reason_code": c, "note": "n"} for i, c in excluded],
            "unanswerable": [{"sub_question": q, "reason": r} for q, r in unanswerable],
            "infeasible_reason": why, "needed_data": list(needed)}


class Fake(DataSourceRegistry):
    def __init__(self, cat): self.cat = cat
    def catalog(self): return self.cat
    def load(self, i): raise KeyError(i)


def go(p, out, data=None):
    st = RunState("t", "req", plan=p)
    llm = FakeLLM([out])
    ctx = RunContext(llm, data or SnapshotRegistry(), Trace("t", None))
    s2_select.run(st, ctx)
    return st, llm


def ids(st, key="selected"):
    return {x["dataset_id"] for x in st.selection[key]}


def test_select_and_exclude():
    st, llm = go(plan(), llm_out([(TRADE, ["averagePrice"])], [(CIT, "irrelevant")]))
    assert ids(st) == {TRADE} and st.status is None
    ex = {x["dataset_id"]: x for x in st.selection["excluded"]}
    assert ex[CIT]["reason_code"] == "irrelevant" and ex["jdh_agri_trade_moving_avg"]["by"] == "rule"
    # LLM 입력에는 id enum과 요약만, 데이터 값(notes)은 없다
    enum = llm.calls[0]["schema"]["properties"]["selected"]["items"]["properties"]["dataset_id"]["enum"]
    assert set(enum) == {CIT, TRADE, "jdh_agri_trade_moving_avg", "synthetic_aws_daily", "jeju_vegetable_cultivation"}
    assert "notes" not in llm.calls[0]["user"] and "averagePrice" in llm.calls[0]["user"]


def test_granularity_sido_only_excluded_even_if_llm_wrong():
    cat = [{"id": "sido", "title": "시도 통계", "spatial_unit": "시도", "columns": [{"name": "v"}], "coverage": {}}]
    st, _ = go(plan(needs={"point_analysis": True}), llm_out([("sido", ["v"])]), Fake(cat))
    assert st.status == "infeasible" and st.selection["excluded"][0]["reason_code"] == "granularity_mismatch"
    assert st.needed_data and any("지점" in n for n in st.needed_data)


def test_sido_is_auxiliary_when_main_exists():
    cat = [{"id": "sido", "spatial_unit": "시도", "columns": [{"name": "v"}], "coverage": {}},
           {"id": "pt", "spatial_unit": "point", "columns": [{"name": "w"}], "coverage": {}}]
    st, _ = go(plan(needs={"point_analysis": True}), llm_out([("sido", ["v"]), ("pt", ["w"])]), Fake(cat))
    roles = {s["dataset_id"]: s["role"] for s in st.selection["selected"]}
    assert roles == {"sido": "auxiliary", "pt": "primary"} and not st.unanswered


def test_out_of_period_and_missing_columns():
    st, _ = go(plan(period="2020년"), llm_out([(TRADE, ["averagePrice"])]))
    assert st.status == "infeasible" and st.selection["excluded"][0]["reason_code"] == "out_of_period"
    st, _ = go(plan(), llm_out([(TRADE, ["없는컬럼"])]))
    assert st.status == "infeasible" and st.selection["excluded"][0]["reason_code"] == "missing_columns"


def test_partial_jeju_city_citrus():
    st, _ = go(plan(location={"text": "제주시"}, needs={"point_analysis": True}),
               llm_out([(CIT, ["노지온주(보통)"]), (TRADE, ["averagePrice"])]))
    assert st.status is None and ids(st) == {TRADE}  # 러너가 unanswered를 보고 partial로 끝낸다
    ex = {x["dataset_id"]: x["reason_code"] for x in st.selection["excluded"]}
    assert ex[CIT] == "out_of_region"
    assert any("서귀포" in u["why"] for u in st.unanswered)
    assert any("지점" in u["what"] for u in st.unanswered)  # 지점 단위 데이터 없음도 기록


def test_infeasible_with_needed_data():
    st, _ = go(plan(crop="마늘", location={"text": "제주시"}),
               llm_out(feasible=False, why="맞는 데이터 없음", needed=["제주시 마늘 재배 면적"]))
    assert st.status == "infeasible" and st.needed_data == ["제주시 마늘 재배 면적"]


def test_unknown_id_blocked():
    # 스키마 enum이 막고, 어댑터가 뚫려도 규칙이 버린다
    st, _ = go(plan(), llm_out([("made_up", []), (TRADE, [])]))
    assert ids(st) == {TRADE}
    assert "made_up" not in ids(st, "excluded")


def test_candidate_reduction():
    cat = [{"id": f"d{i}", "title": f"기상 관측 {i}", "columns": [], "coverage": {}} for i in range(34)]
    cat += [{"id": f"c{i}", "title": f"감귤 생산 {i}", "columns": [], "coverage": {}} for i in range(6)]
    cand = reduce_candidates(plan(), cat)
    assert len(cand) == 20 and all(e["id"].startswith("c") for e in cand[:6])
    st, llm = go(plan(), llm_out([("c0", [])]), Fake(cat))
    enum = llm.calls[0]["schema"]["properties"]["selected"]["items"]["properties"]["dataset_id"]["enum"]
    assert len(enum) == 20 and len(st.selection["excluded"]) == 39
    assert len(reduce_candidates(plan(), cat[:30])) == 30


def test_empty_catalog_passthrough():
    st, llm = go(plan(), {}, Fake([]))
    assert st.status is None and st.selection is None and not llm.calls


def _rel(plausible, asked=True, reason="연결할 근거가 없는 조합입니다."):
    return {**llm_out(selected=[(CIT, []), (TRADE, [])]), "relation": {"asked": asked, "plausible": plausible, "reason": reason}}


def test_implausible_relation_is_infeasible_with_reason():
    st, _ = go(plan(), _rel(False))
    assert st.status == "infeasible" and st.reason == "연결할 근거가 없는 조합입니다."
    assert st.needed_data == ["각 데이터를 따로 분석하는 요청"]


def test_plausible_or_unasked_relation_passes():
    assert go(plan(), _rel(True))[0].status is None
    assert go(plan(), _rel(False, asked=False))[0].status is None   # 관계를 묻지 않았으면 판단하지 않는다
    assert go(plan(), llm_out(selected=[(CIT, [])]))[0].status is None   # relation 누락도 통과
