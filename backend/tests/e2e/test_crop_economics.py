"""티켓 17: 채소 재배현황 분석. 가짜 LLM, 키·네트워크 없음. 모듈 계산 검증 + 종단 간 시나리오."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from fakes import COL, respond

from jejuagent.catalog.crop_map import crop_for_cultivar
from jejuagent.geo import dem
from jejuagent.llm import FakeLLM
from jejuagent.modules_lib import ModuleStore
from jejuagent.runner import run_agent
from jejuagent.runner.datasource import SnapshotRegistry

DS = "jeju_vegetable_cultivation"
MID = "market-crop-economics"
ROLES = {"season": "연산", "crop_group": "채소구분대분류", "crop": "채소구분소분류",
         "area": "면적(ha)", "production": "생산량(톤)", "revenue": "조수입(백만원)"}
CLICK = {"lat": 33.5170, "lon": 126.5300}


def cultivation():
    return SnapshotRegistry().load(DS)


def _seed():
    p = Path(__file__).resolve().parents[2] / "jejuagent" / "modules_seed" / "market" / "crop_economics.py"
    spec = importlib.util.spec_from_file_location("ce", p)
    m = importlib.util.module_from_spec(spec)
    m.DataProblem = type("DataProblem", (Exception,), {})    # 격리 실행기가 넣어 주는 내장 예외
    spec.loader.exec_module(m)
    return m


def test_loader_reads_seasons_groups_and_28_crops():
    df = cultivation()
    assert len(df) == 168 and df.attrs["encoding"] == "utf-8"
    assert sorted(df["연산"].unique()) == ["15-16", "16-17", "17-18", "18-19", "19-20", "20-21"]
    assert set(df["채소구분대분류"]) == {"노지채소", "시설채소"} and df["채소구분소분류"].nunique() == 28
    assert df["면적(ha)"].dtype == float
    assert df["채소구분소분류"].map(lambda s: s.startswith("기타")).sum() == 12      # 기타 2종 x 6연산


def test_module_units_ranking_and_limits():
    m = _seed()
    df = cultivation()
    inp = {"cultivation": pd.DataFrame({k: df[c] for k, c in ROLES.items()})}
    out = m.run(inp, {})
    assert m.check(out, inp) == []
    x = out["crop_metrics"].query("season == '20-21' and crop == '월동무'").iloc[0]
    assert x.revenue_per_ha_mw == 21.05                      # 106434 / 5056
    assert x.yield_t_per_ha == 71.12                         # 359575 / 5056
    assert x.unit_price_won_per_kg == 296.0                  # 106434 x 1e6 / (359575 x 1e3)
    r = out["crop_ranking"]
    assert set(r.crop_group) == {"노지채소", "시설채소"} and not r.crop.str.startswith("기타").any()
    assert r[r.crop_group == "노지채소"].iloc[0].crop == "잎쪽파"   # 95.42백만원/ha, 구마늘은 3위(53.27)
    assert out["crop_metrics"][out["crop_metrics"].crop.str.startswith("기타")].is_aggregate.all()
    t = out["crop_area_trend"].query("crop == '월동무' and crop_group == '노지채소'")
    assert len(t) == 6 and pd.isna(t.iloc[0].area_change_pct)
    lim = " ".join(out["limitations"].text)
    for s in ("도 전체", "순이익", "2021-08-09", "20-21", "보장하지 않"):
        assert s in lim


def test_crop_name_map_only_exact():
    assert crop_for_cultivar("월동무") == "월동무"
    assert crop_for_cultivar("당근(일반)") is None and crop_for_cultivar("깐마늘") is None


def _crop_llm(selected):
    def r(system, user):
        if "요청 규격화 담당" in system:
            p = respond(system, user)
            p["crop"] = None
            p["needs"] = {"point_analysis": "여기" in user, "time_series": False, "spatial_comparison": False}
            return p
        if "데이터 선택 담당" in system:
            return {"feasible": True, "selected": [{"dataset_id": i, "reason": "r", "columns": []} for i in selected],
                    "excluded": [], "unanswerable": [], "infeasible_reason": "", "needed_data": []}
        if "작업 계획자" in system:
            if "jeju_weather_daily" in selected:
                return respond(system, user)
            return {"tasks": [{"id": "econ", "title": "작목별 면적당 조수입과 재배면적 추세",
                               "description": "채소 재배현황의 작목별 면적당 조수입, 수량, 단가, 재배면적 증감과 순위",
                               "inputs": [DS], "outputs": [
                                   {"id": "crop_metrics", "kind": "table", "description": "작목·연산별 지표", "columns": [COL("crop", "str")]},
                                   {"id": "crop_ranking", "kind": "table", "description": "작목 순위", "columns": [COL("crop", "str")]},
                                   {"id": "crop_area_trend", "kind": "series", "description": "재배면적 추세", "columns": [COL("season", "str")]},
                                   {"id": "limitations", "kind": "table", "description": "한계", "columns": [COL("text", "str")]}]}]}
        if "기존 모듈을 쓸지" in system:
            if "[작업] 지점 기후" in user:
                return respond(system, user)
            return {"decision": "reuse", "module_id": MID, "reason": "verified 모듈이 맞다",
                    "input_binding": [{"module_input": "cultivation", "task_input": DS}],
                    "role_mapping": [{"input": "cultivation", "role": k, "column": c} for k, c in ROLES.items()]}
        if "보고서로 설계하는 담당" in system and "crop_ranking" in user:
            blk = [{"artifact_id": None, "x": None, "y": [], "chart_type": "line", "title": None, "steps": [], "text": None, **b}
                   for b in ({"type": "table", "artifact_id": "crop_ranking", "title": "면적당 조수입 순위"},
                             {"type": "chart", "artifact_id": "crop_area_trend", "x": "season", "y": ["area_ha"], "title": "재배면적 추세"})]
            return {"title": "작목별 면적당 조수입", "summary": "조수입 기준 순위입니다.", "limits": [],
                    "sections": [{"heading": "결과", "text": "도 전체 기준입니다.", "blocks": blk}]}
        return respond(system, user)
    return FakeLLM([r] * 100)


def go(tmp_path, req, selected, click=None):
    return run_agent(req, llm=_crop_llm(selected), data=SnapshotRegistry(), click=click, runs_dir=tmp_path / "runs",
                     modules=ModuleStore(tmp_path / "store"))


@pytest.mark.parametrize("q", ["뭘 늘리면 좋을까?", "마늘이랑 양파 중 면적당 조수입이 나은 건?"])
def test_location_free_questions_use_cultivation_data(tmp_path, q):
    res = go(tmp_path, q, [DS])
    st = res.state
    assert res.status == "answered", (res.status, res.message, st.unanswered, [t["failure"] for t in st.tasks])
    assert [s["dataset_id"] for s in st.selection["selected"]] == [DS] and not st.unanswered
    assert st.tasks[0]["module"]["decision"] == "reuse" and st.tasks[0]["module"]["status"] == "verified"
    assert 'data-map="' not in res.html and "구마늘" in res.html
    for s in ("도 전체", "순이익", "2021-08-09", "20-21", "보장하지 않"):
        assert s in res.html, s


@pytest.mark.skipif(not dem._files(), reason="DEM 도엽 없음")
def test_point_question_uses_cultivation_only_as_auxiliary(tmp_path):
    res = go(tmp_path, "제주시 여기에 어떤 작목이 좋을까?", ["jeju_weather_daily", DS], click=CLICK)
    st = res.state
    assert {s["dataset_id"]: s["role"] for s in st.selection["selected"]} == {"jeju_weather_daily": "primary", DS: "auxiliary"}
    assert not any("지점 단위" in u["what"] for u in st.unanswered)


def test_cultivation_alone_cannot_do_point_analysis(tmp_path):
    res = go(tmp_path, "제주시 여기에 어떤 작목이 좋을까?", [DS], click=CLICK)
    assert res.status == "infeasible"
    assert {x["dataset_id"]: x["reason_code"] for x in res.state.selection["excluded"]}[DS] == "granularity_mismatch"
