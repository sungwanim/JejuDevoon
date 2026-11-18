"""모듈 라이브러리 경계 테스트. Runner 경계(run_agent)에서 가짜 LLM이 결정과 코드를 돌려준다. 키·네트워크 불필요.

① 요청 규격화·② 선택은 가짜 단계, ③ 로드와 ④ 분석은 진짜 단계. 라이브러리는 tasks._library를 임시 저장소로 바꿔 켠다.
"""
import json
import types

import pandas as pd
import pytest

from jejuagent.analysis import tasks as tasks_mod
from jejuagent.catalog.profile import profile
from jejuagent.llm import FakeLLM
from jejuagent.modules_lib import ModuleStore, catalog_summary_table, code_has_pii, scrub, search
from jejuagent.modules_lib.store import SEED_ROOT
from jejuagent.runner import run_agent
from jejuagent.runner.datasource import SnapshotRegistry
from jejuagent.runner.pipeline import Stage
from jejuagent.runner.stages import s3_load, s4_analyze
from jejuagent.sandbox import run_generated_code

DS, DS2 = "jdh_agri_daily_trade", "jdh_agri_trade_moving_avg"
COL = lambda n, d, u="": {"name": n, "dtype": d, "unit": u, "min": None, "max": None}  # noqa: E731
OUT = {"id": "radish_price_trend", "kind": "series", "description": "월동무 일별 가격과 이동평균",
       "columns": [COL("date", "date"), COL("price", "float", "원/kg"), COL("ma7", "float", "원/kg")]}


def task(ds, tid="t1"):
    return {"id": tid, "title": "월동무 가격 시계열", "description": "월동무 일별 평균 도매가격과 이동평균", "inputs": [ds],
            "outputs": [OUT]}


CODE = '''
MANIFEST = {"title": "품종 가격 시계열", "description": "품종 일별 도매가격과 이동평균", "tags": ["price"],
            "input_roles": {"jdh_agri_daily_trade": {"date": "date", "variety": "str", "price": "float"}},
            "params": {}, "outputs": ["radish_price_trend"]}
def run(inputs, params):
    df = inputs["jdh_agri_daily_trade"]
    df = df[df["variety"] == "월동무"].dropna(subset=["price"]).sort_values("date")
    if df.empty:
        raise DataProblem("월동무 행이 없다")
    out = df[["date", "price"]].copy()
    out["ma7"] = out["price"].rolling(7, min_periods=1).mean()
    return {"radish_price_trend": out.reset_index(drop=True)}
def check(outputs, inputs):
    o = outputs["radish_price_trend"]
    return [] if len(o) > 0 and o["price"].notna().all() else ["가격이 비었다"]
'''
MAP1 = [{"input": DS, "role": "date", "column": "baseDate"}, {"input": DS, "role": "variety", "column": "cultivar"},
        {"input": DS, "role": "price", "column": "averagePrice"}]
MAP2 = [{"input": DS, "role": "date", "column": "baseDate"}, {"input": DS, "role": "variety", "column": "cultivar"},
        {"input": DS, "role": "price", "column": "priceMovingAverage"}]       # 컬럼 이름이 다른 비슷한 데이터
BIND2 = [{"module_input": DS, "task_input": DS2}]


class Trimmed(SnapshotRegistry):
    """데이터 버전 해시가 달라지도록 앞 행을 잘라낸 같은 스냅샷."""

    def load(self, dataset_id):
        return super().load(dataset_id).iloc[100:].reset_index(drop=True)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = ModuleStore(tmp_path / "store", seed_dirs=[])
    monkeypatch.setattr(tasks_mod, "_library", lambda ctx: s)
    return s


def go(tmp_path, responses, tasks, ds=DS, reg=None, goal="월동무 최근 가격 추세"):
    def setup(state, ctx):
        state.plan = {"goal": goal, "sub_questions": []}
        state.selection = {"selected": [{"dataset_id": ds, "reason": "가격", "columns": []}]}
        return state
    stages = [Stage("s1_parse", types.SimpleNamespace(run=setup)), Stage("s3_load", s3_load),
              Stage("s4_analyze", s4_analyze)]
    llm = FakeLLM([{"tasks": tasks}, *responses])
    res = run_agent("요청", llm=llm, data=reg or SnapshotRegistry(), runs_dir=tmp_path / "runs", stages=stages)
    return res, llm


def decision(kind, module_id="", binding=(), mapping=()):
    return {"decision": kind, "module_id": module_id, "reason": "테스트", "input_binding": list(binding),
            "role_mapping": list(mapping)}


def first_run(tmp_path, store, **kw):
    res, _ = go(tmp_path, [{"code": CODE, "role_mapping": MAP1}], [task(DS)], **kw)
    assert res.status == "answered"
    return res.state.tasks[0]["module"]["saved"]


# ---------------------------------------------------------------- 저장

def test_new_code_is_saved_as_auto_with_metadata_and_scrubbed_goal(tmp_path, store):
    saved = first_run(tmp_path, store, goal="김철수 씨 농가(010-1234-5678, 33.49961 126.53123, serviceKey=abc123) 월동무 추세")
    mid, ver = saved.split("@v")
    m = store.get(mid, int(ver))
    assert m.status == "auto" and m.version == 1 and m.title == "품종 가격 시계열"
    assert m.validation["mock"] and m.validation["real"] and m.model == "fake"
    assert m.tested_on[0]["dataset_id"] == DS and len(m.tested_on[0]["version_hash"]) == 16
    assert m.input_roles[DS]["price"] == "float" and m.output_schema[0]["id"] == "radish_price_trend"
    assert m.output_schema[0]["columns"][1] == {"name": "price", "dtype": "float", "unit": "원/kg"}
    for bad in ("김철수", "010-1234", "33.4996", "126.531", "abc123"):
        assert bad not in m.goal and bad not in (store.root / mid / "v1" / "meta.json").read_text(encoding="utf-8")
    assert "월동무" in m.goal
    assert (store.root / mid / "v1" / "module.py").read_text(encoding="utf-8") == CODE


def test_scrub_rules_and_pii_code_is_not_saved(store):
    assert scrub("연락 user@example.com, 서귀포 123-4번지, 이름: 홍길동, " + "sk" + "-abcdefgh12345678") == \
        "연락 [이메일], 서귀포 [주소], 이름: [이름], [키]"
    assert scrub("박영희님이 33.1234,126.9876 에서") == "[이름]님이 [좌표],[좌표] 에서"
    assert scrub("감귤 가격 추세") == "감귤 가격 추세"
    assert code_has_pii(CODE + '\nAPI_KEY = "test-key"') and code_has_pii("x = 33.49961") and not code_has_pii(CODE)
    assert store.save(CODE + '\nSERVICE_KEY = "test-key"', task=task(DS), tested_on=[]) is None


def test_same_code_is_deduplicated(tmp_path, store):
    saved = first_run(tmp_path, store)
    res, _ = go(tmp_path, [decision("new"), {"code": CODE + "\n# 주석", "role_mapping": MAP1}], [task(DS)])
    assert res.state.tasks[0]["module"]["saved"] == saved and len(store.all()) == 1


# ---------------------------------------------------------------- 검색

def test_verified_beats_auto_and_incompatible_roles_are_excluded(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "s.py").write_text(CODE.replace("MANIFEST = {", 'MANIFEST = {"id": "seed-x", "version": 1, ', 1),
                               encoding="utf-8")
    s = ModuleStore(tmp_path / "store", seed_dirs=[seed])
    s.save(CODE.replace("rolling(7", "rolling(5"), task=task(DS), tested_on=[])
    profs = {DS2: profile(SnapshotRegistry().load(DS2), DS2)}
    cands = search(s, "월동무 일별 평균 도매가격과 이동평균", profs, n_outputs=1)
    assert [c.module.status for c in cands] == ["verified", "auto"]
    assert cands[0].binding == {DS: DS2}
    no_price = {"x": profile(pd.DataFrame({"a": ["u", "v"], "b": ["u", "v"]}), "x")}
    assert search(s, "월동무 일별 평균 도매가격과 이동평균", no_price) == []         # 필요한 역할을 못 채움


# ---------------------------------------------------------------- 재사용 / 수정 / 해시 변경

def test_reuse_with_different_column_names_reverifies_and_skips_codegen(tmp_path, store):
    mid = first_run(tmp_path, store).split("@v")[0]
    res, llm = go(tmp_path, [decision("reuse", mid, BIND2, MAP2)], [task(DS2, "t9")], ds=DS2)
    t = res.state.tasks[0]
    assert res.status == "answered" and t["status"] == "ok" and t["module"]["decision"] == "reuse"
    assert [c["purpose"] for c in llm.calls] == ["s4_plan_tasks", "s4_module_decision:t9"]     # 코드 생성 호출 없음
    a = res.state.artifacts["radish_price_trend"]
    assert a.role_mapping == {DS2: {"date": "baseDate", "variety": "cultivar", "price": "priceMovingAverage"}}
    assert a.source_ids == [DS2] and len(a.value) > 20 and a.value["price"].notna().all()
    assert [x["kind"] for x in t["attempts"]] == ["reuse"] and t["attempts"][0]["phase"] == "real"   # 검증을 다시 돌렸다
    assert store.get(mid).tested_on[-1]["dataset_id"] == DS2


def test_reuse_failure_falls_back_to_revise_with_reference_code(tmp_path, store):
    mid = first_run(tmp_path, store).split("@v")[0]
    bad = [{**m, "column": "없는컬럼"} if m["role"] == "price" else m for m in MAP2]
    res, llm = go(tmp_path, [decision("reuse", mid, BIND2, bad), {"code": CODE.replace("rolling(7", "rolling(3").replace(DS, DS2),
                                                                    "role_mapping": [{**m, "input": DS2} for m in MAP2]}], [task(DS2)], ds=DS2)
    t = res.state.tasks[0]
    assert res.status == "answered" and [x["kind"] for x in t["attempts"]] == ["reuse", "revise"]
    assert t["attempts"][0]["failure"] == "column_role_mismatch" and "reuse_failed" in t["module"]
    assert "[참고 모듈" in llm.calls[-1]["user"] and "[그대로 재사용했더니 실패]" in llm.calls[-1]["user"]
    assert t["module"]["saved"].endswith("@v2")


def test_revise_creates_new_version_of_same_module(tmp_path, store):
    mid = first_run(tmp_path, store).split("@v")[0]
    res, llm = go(tmp_path, [decision("revise", mid), {"code": CODE.replace("rolling(7", "rolling(14"),
                                                       "role_mapping": MAP1}], [task(DS)])
    t = res.state.tasks[0]
    assert t["attempts"][0]["kind"] == "revise" and t["module"]["saved"] == f"{mid}@v2"
    assert "rolling(7" in llm.calls[-1]["user"]                      # 기존 코드가 참고 자료로 넘어갔다
    assert [m.version for m in store.versions(mid)] == [1, 2] and "rolling(14" in store.get(mid).code


def test_data_version_hash_change_discards_cached_result_but_reverifies_code(tmp_path, store):
    mid = first_run(tmp_path, store).split("@v")[0]

    def reuse(reg):
        res, _ = go(tmp_path, [decision("reuse", mid, [{"module_input": DS, "task_input": DS}], MAP1)], [task(DS)], reg=reg)
        t = res.state.tasks[0]
        assert t["status"] == "ok"
        return t["module"]["cache"], t["attempts"][0]["phase"], len(res.state.artifacts["radish_price_trend"].value)

    c1 = reuse(SnapshotRegistry())
    c2 = reuse(SnapshotRegistry())
    c3 = reuse(Trimmed())                      # 데이터 버전 해시가 바뀜
    assert c1[:2] == ("miss", "real") and c2[:2] == ("hit", "cache")
    assert c3[:2] == ("miss", "real")          # 이전 결과는 버려지고 코드는 새 데이터로 다시 검증됐다
    assert len({t["version_hash"] for t in store.get(mid).tested_on}) == 2


# ---------------------------------------------------------------- verified 시드

def test_verified_price_module_reproduces_from_snapshot_without_codegen(tmp_path, monkeypatch):
    s = ModuleStore(tmp_path / "store")                       # 기본 시드 폴더(market/ + 다른 티켓의 시드)
    monkeypatch.setattr(tasks_mod, "_library", lambda ctx: s)
    mid = "market-price-trend-volatility"
    assert s.get(mid).status == "verified" and s.get(mid).reviewed_by
    t = {"id": "t1", "title": "품목별 가격 추세와 변동성", "description": "품목별 일별 도매가격의 변화율과 변동성",
         "inputs": [DS], "outputs": [{"id": "stats", "kind": "table", "description": "품목별 추세", "columns": []},
                                     {"id": "daily", "kind": "series", "description": "일별 가격", "columns": []}]}
    mp = [{"input": "trade", "role": r, "column": c} for r, c in
          (("date", "baseDate"), ("variety", "cultivar"), ("price", "averagePrice"))]
    res, llm = go(tmp_path, [decision("reuse", mid, [{"module_input": "trade", "task_input": DS}], mp)], [t])
    assert res.status == "answered" and len(llm.calls) == 2
    stats = res.state.artifacts["stats"].value
    assert len(stats) == 6 and (stats["volatility_pct"] > 0).all() and (stats["last_price"] > 0).all()
    assert res.state.tasks[0]["module"]["candidates"][0][:2] == (mid, "verified")
    assert not list((tmp_path / "store").glob("*/v*/module.py"))         # 시드 재사용은 auto 모듈을 만들지 않는다
    # 같은 스냅샷이면 결과가 같다 (결정적)
    again, _ = go(tmp_path, [decision("reuse", mid, [{"module_input": "trade", "task_input": DS}], mp)], [t])
    pd.testing.assert_frame_equal(stats, again.state.artifacts["stats"].value)


def test_verified_catalog_explorer_runs_on_catalog_summary_table():
    code = (SEED_ROOT / "market" / "catalog_explorer.py").read_text(encoding="utf-8")
    table = catalog_summary_table(SnapshotRegistry().catalog())
    schema = ModuleStore(seed_dirs=[SEED_ROOT / "market"]).get("market-catalog-explorer").output_schema
    mock = run_generated_code(code, None, {}, profiles={"catalog": profile(table, "catalog")}, artifacts=schema)
    real = run_generated_code(code, {"catalog": table}, {}, artifacts=schema)
    assert mock.ok, mock.message
    assert real.ok, real.message
    assert real.outputs["catalog_counts"]["n_datasets"] == len(table) == 8
    assert real.outputs["catalog_overview"]["span_days"].iloc[0] > 0
    assert json.dumps(real.outputs["catalog_counts"])
