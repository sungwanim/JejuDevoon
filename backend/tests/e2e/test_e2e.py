"""티켓 16: 종단 간(① 규격화 -> ⑤ 렌더) 시나리오. 가짜 LLM(fakes.py), 키·네트워크 없음. 실제 샌드박스와 모듈 라이브러리를 쓴다."""
import html

import pytest
from fakes import make_llm

from jejuagent.criteria.loader import load_criteria
from jejuagent.geo import dem, is_land
from jejuagent.modules_lib import ModuleStore
from jejuagent.runner import run_agent
from jejuagent.runner.datasource import SnapshotRegistry

pytestmark = pytest.mark.skipif(not dem._files(), reason="DEM 도엽 없음")
SOUTH, CITY = {"lat": 33.30, "lon": 126.55}, {"lat": 33.5170, "lon": 126.5300}   # 서귀포 쪽 내륙, 제주시 해안
SYN = "합성 샘플 데이터로 만든 결과입니다"


def go(tmp_path, req, click=None, prev=None):
    llm = make_llm()
    res = run_agent(req, llm=llm, data=SnapshotRegistry(), click=click, prev=prev, runs_dir=tmp_path / "runs",
                    modules=ModuleStore(tmp_path / "store"))
    return res, llm


def test_clicks_are_on_land():
    assert is_land(**SOUTH) and is_land(**CITY)


def test_click_and_radish_question_gives_map_with_site_climate_and_price(tmp_path):
    res, llm = go(tmp_path, "여기에 월동무 어때? 최근 시세도 같이 알려줘", SOUTH)
    st, html = res.state, res.html
    assert res.status == "answered", (res.status, res.message, st.unanswered, [t["failure"] for t in st.tasks])
    # 지점 질문인데 '지점 단위 분석 불가'가 붙지 않는다 (관측소 데이터가 카탈로그에 있다)
    assert not any("지점 단위" in u["what"] for u in st.unanswered)
    # ③과 ④ 사이: 부모가 DEM 고도를 계산해 입력에 넣었다
    assert st.profiles["site_point"]["n_rows"] == 1 and st.data["site_point"].elevation_m.iloc[0] > 0
    # LLM 코드 생성 없이 verified 모듈 두 개(지점 기후 + 시세)가 재사용되었다
    assert [t["module"]["decision"] for t in st.tasks] == ["reuse", "reuse"]
    assert {t["module"]["status"] for t in st.tasks} == {"verified"}
    assert not [c for c in llm.calls if "codegen" in c["purpose"] or "revise" in c["purpose"]]
    assert st.artifacts["site_markers"].kind == "geo" and len(st.artifacts["site_markers"].value) == 13   # 지점 1 + 관측소 12
    # 지도 HTML: 지도 블록, 관측소 마커, 지점 기후 지표(고도·교차검증), 시세 차트
    assert 'data-map="' in html and "SYN01" in html and "선택 지점(추정)" in html
    assert "elevation_m" in html and "idw_lapse_fixed" in html and "data-chart" in html
    # 합성 경고가 제목보다 위에 있다. 한계 문구에 적합도 미판정이 들어간다
    assert SYN in html and html.index(SYN) < html.index("<h1")
    assert "재배 적합도는 공공데이터셋 근거가 없어 판정하지 않는다" in html
    assert "합성 데이터로 계산한 결과다" in html                       # 모듈 출력의 합성 표시(파라미터로 전달됨)
    # 기본 상태에서는 문헌 기준 적합도(충족 여부·출처)가 나오지 않는다
    su = st.artifacts["suitability"].value
    assert su.result.eq("근거 부족").all() and su.source_title.eq("").all() and "충족" not in html
    assert not any(s.title in html for s in load_criteria().sources.values())


def test_suitability_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("JEJU_SUITABILITY", "1")
    res, _ = go(tmp_path, "여기에 월동무 어때?", SOUTH)
    s = res.state.artifacts["suitability"].value
    assert res.status == "answered" and len(s) > 0 and s.source_title.ne("").any()
    assert s.crop.eq("무").all() and html.escape(s.source_title.iloc[0]) in res.html


def test_missing_location_clarifies_then_continues(tmp_path):
    res, _ = go(tmp_path, "월동무 어때?")
    assert res.status == "clarify" and "클릭" in res.state.reason and res.html is None
    res2, llm = go(tmp_path, "여기요", SOUTH, prev={"plan": res.state.plan, "request": "월동무 어때?"})
    assert res2.status == "answered" and 'data-map="' in res2.html
    assert "월동무 어때?" in llm.calls[0]["user"]


def test_out_of_domain_is_infeasible(tmp_path):
    res, _ = go(tmp_path, "주식 추천해줘")
    assert res.status == "infeasible" and res.html is None and res.state.needed_data


def test_sea_click_is_infeasible_with_message(tmp_path):
    res, _ = go(tmp_path, "여기에 월동무 어때?", {"lat": 33.9, "lon": 126.5})
    assert res.status == "infeasible" and "범위" in res.message


def test_jeju_city_citrus_is_partial_with_seogwipo_only_notice(tmp_path):
    res, _ = go(tmp_path, "제주시 여기에 감귤 어때?", CITY)
    st = res.state
    assert res.status == "partial", (res.status, res.message, st.unanswered)
    assert any(x["dataset_id"] == "seogwipo_citrus_production" and x["reason_code"] == "out_of_region"
               for x in st.selection["excluded"])
    assert any("서귀포" in u["why"] for u in st.unanswered)
    assert "서귀포" in res.html and 'data-map="' in res.html and SYN in res.html
    assert "답하지 못한 부분" in res.html


def test_fallback_notice_reaches_the_user(tmp_path):
    class Fallback(SnapshotRegistry):
        def load(self, dataset_id):
            df = super().load(dataset_id)
            if dataset_id == "jdh_agri_daily_trade":
                df.attrs.update(data_mode="fallback", fallback_reason={"cause": "API 키가 설정되지 않았습니다.", "fix": ".env에 키를 넣으세요."})
            return df
    res = run_agent("여기에 월동무 어때? 최근 시세도 같이 알려줘", llm=make_llm(), data=Fallback(), click=SOUTH,
                    runs_dir=tmp_path / "runs", modules=ModuleStore(tmp_path / "store"))
    assert "저장된 스냅샷을 썼습니다" in res.html and "API 키가 설정되지 않았습니다" in res.html
    assert res.state.extra["notices"]


def test_api_wires_registry_modules_and_notices(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("JEJU_LLM", "fake")
    monkeypatch.setenv("JEJU_DATA_MODE", "live")
    main = importlib.reload(importlib.import_module("jejuagent.api.main"))
    assert len(TestClient(main.app).get("/api/catalog").json()) == 5
    from jejuagent.data.live import LiveRegistry
    from jejuagent.runner.datasource import make_registry
    assert isinstance(make_registry(), LiveRegistry)
    monkeypatch.delenv("JEJU_DATA_MODE")
    assert type(make_registry()) is SnapshotRegistry
