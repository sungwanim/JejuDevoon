"""⑤ 렌더 경계 테스트: Runner 경계(run_agent)에서 가짜 LLM이 ReportSpec을 낸다. 키·네트워크 불필요.

①~④는 가짜 단계가 상태를 채워 대신하고, ⑤는 진짜 단계를 쓴다.
"""
import re
import types

import pandas as pd
import pytest

from jejuagent.analysis.artifact import Artifact
from jejuagent.llm import FakeLLM, LLMError
from jejuagent.render.numbers import check_sentence, extract_numbers, grounded_numbers
from jejuagent.runner import Limits, run_agent
from jejuagent.runner.datasource import SnapshotRegistry
from jejuagent.runner.pipeline import Stage
from jejuagent.runner.stages import s5_render

DS = "jdh_agri_daily_trade"
SERIES = pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "price": [1000.0, 1100.0, 1234.5]})
GEO = pd.DataFrame({"lat": [33.4, 33.5], "lon": [126.5, 126.6], "name": ["가", "나"]})


def art(i, kind, value, **kw):
    return Artifact(id=i, kind=kind, value=value, description=kw.get("description", i), columns=[], source_ids=[DS],
                    task_id="t1", module_title="가격 시계열", code_hash="abc123def4567890", code="")


def block(**kw):
    return {"type": "callout", "artifact_id": None, "x": None, "y": [], "chart_type": "line", "title": None,
            "steps": [], "text": None, **kw}


def spec(**kw):
    return {"title": "월동무 가격", "summary": "가격이 올랐습니다.", "sections": [], "limits": [], **kw}


def go(tmp_path, responses, fmt="report", unanswered=(), tasks_status="ok", limits=None, plan_extra=None,
       with_artifacts=True, selected=(DS,), excluded=(), request="월동무 가격 알려줘"):
    def setup(state, ctx):
        state.plan = {"goal": "월동무 가격 추세", "sub_questions": [], "output_format": fmt, "style": "report",
                      "needs": {"point_analysis": fmt == "map"}, "location": {"lat": 33.4, "lon": 126.5, "text": "한림"},
                      "crop": "월동무", "notice": None, **(plan_extra or {})}
        state.selection = {"selected": [{"dataset_id": d, "reason": "가격 데이터", "role": "primary"} for d in selected],
                           "excluded": list(excluded)}
        if with_artifacts:
            state.artifacts = {"price_series": art("price_series", "series", SERIES),
                               "stats": art("stats", "metrics", {"last_price": 1234.5, "change_pct": 23.45}),
                               "sites": art("sites", "geo", GEO)}
            state.tasks = [{"id": "t1", "title": "가격 시계열", "status": tasks_status, "attempts": [{}, {}],
                            "artifact_ids": ["price_series", "stats", "sites"]}]
        state.unanswered.extend(unanswered)
        return state
    stages = [Stage("s1_parse", types.SimpleNamespace(run=setup)), Stage("s5_render", s5_render)]
    llm = FakeLLM(responses)
    res = run_agent(request, llm=llm, data=SnapshotRegistry(), runs_dir=tmp_path, stages=stages, limits=limits)
    return res, llm


FULL = spec(sections=[{"heading": "가격 추이", "text": "가격이 꾸준히 올랐습니다.", "blocks": [
    block(type="chart", artifact_id="price_series", x="date", y=["price"]),
    block(type="table", artifact_id="stats"),
    block(type="flow", steps=["데이터 불러오기", "가격 계산"]),
    block(type="map", artifact_id="sites"),
    block(type="callout", text="최근 값을 확인하세요.")]}], limits=["데이터 기간이 짧습니다."])
COMMON = ["사용한 데이터", "제외한 데이터와 이유", "분석 과정", "근거와 한계", "데이터 출처와 이용조건", "답하지 못한 부분과 이유"]


@pytest.mark.parametrize("fmt,marker", [("report", ">요약<"), ("visual", ">큰 결론<"), ("map", 'data-map="b')])
def test_three_formats_with_common_sections(tmp_path, fmt, marker):
    res, llm = go(tmp_path, [FULL], fmt=fmt)
    assert res.status == "answered" and marker in res.html
    assert res.html.count("<!doctype html>") == 1 and 'class="fmt-' + fmt in res.html
    for s in COMMON:
        assert s in res.html, s
    assert "radish" not in res.html and "가격 시계열" in res.html and "abc123def4567890" in res.html  # 모듈·버전
    assert [c["schema_name"] for c in llm.calls] == ["report_spec"]
    assert "mermaid@10.9.3" in res.html and "chart.js@4.4.7" in res.html and "leaflet@1.9.4" in res.html  # 고정 버전 CDN


def test_map_comes_first_in_map_format(tmp_path):
    res, _ = go(tmp_path, [FULL], fmt="map")
    assert res.html.index('id="map"') < res.html.index('id="summary"')


def test_ungrounded_number_sentence_removed(tmp_path):
    bad = spec(summary="가격은 9999원입니다. 가격이 올랐습니다.",
               sections=[{"heading": "추이", "text": "마지막 가격은 1,234.5원이고 첫 거래일은 2024년 1월 2일입니다. 상승률은 77.7%입니다.",
                          "blocks": []}])
    res, _ = go(tmp_path, [bad])
    assert "9999" not in res.html and "77.7" not in res.html
    assert "가격이 올랐습니다." in res.html
    assert "마지막 가격은 1,234.5원" in res.html          # 값과 일치(첨부 단위·쉼표 허용)
    assert any(e["type"] == "decision" and len(e.get("removed_sentences", [])) == 2 for e in res.events)  # trace 기록과 개수 일치


def test_number_rules():
    g = grounded_numbers({"a": art("a", "series", SERIES), "m": art("m", "metrics", {"r": 0.2345})})
    assert check_sentence("가격은 1234.5원, 반올림하면 1,235원입니다.", g)   # 정수 자릿수 반올림
    assert check_sentence("변화율은 23.5%입니다.", g)
    assert not check_sentence("가격은 4321원입니다.", g)
    # 날짜·서수는 오탐하지 않는다
    assert extract_numbers("2024년 3월 15일, 3문장, 1단계, 2번째, 2024-01-02, task3, 1~3월에") == []
    assert extract_numbers("1. 첫째 항목") == []
    assert [v for v, _ in extract_numbers("약 1.2만원과 5%")] == [12000, 5]


def test_no_llm_numbers_in_summary_over_three_sentences(tmp_path):
    res, _ = go(tmp_path, [spec(summary="하나입니다. 둘입니다. 셋입니다. 넷입니다.")])
    assert "셋입니다." in res.html and "넷입니다." not in res.html


def test_invalid_blocks_dropped(tmp_path):
    s = spec(sections=[{"heading": "x", "text": "", "blocks": [
        block(type="chart", artifact_id="nope", x="date", y=["price"]),
        block(type="chart", artifact_id="price_series", x="date", y=["없는열"]),
        block(type="table", artifact_id="ghost")]}])
    res, _ = go(tmp_path, [s])
    assert 'data-chart="b' not in res.html and "ghost" not in res.html


def test_partial_shows_unanswered(tmp_path):
    ua = [{"what": "제주시 감귤 생산", "why": "제주시 데이터가 없다"}]
    res, _ = go(tmp_path, [spec()], unanswered=ua)
    assert res.status == "partial"
    assert "제주시 감귤 생산" in res.html and "제주시 데이터가 없다" in res.html and "일부만 답했습니다" in res.html


def test_failed_task_makes_partial(tmp_path):
    res, _ = go(tmp_path, [spec()], tasks_status="failed")
    assert res.status == "partial"


def test_excluded_and_limit_phrases_and_notice(tmp_path):
    ex = [{"dataset_id": "seogwipo_citrus_production", "reason_code": "out_of_region", "note": "제주시 데이터 없음", "by": "rule"}]
    res, _ = go(tmp_path, [spec()], fmt="map", excluded=ex, plan_extra={"notice": "수익은 보장할 수 없습니다."})
    h = res.html
    assert "수익은 보장할 수 없습니다." in h and "지역이 맞지 않음" in h and "제주시 데이터 없음" in h
    assert "90m" in h and "경사·일사" in h and "한계온도" in h and "제주시 데이터는 없습니다" in h


def test_html_escaping_and_json_safety(tmp_path):
    evil = '<script>alert(1)</script>'
    df = pd.DataFrame({"date": [evil, "</script><b>"], "price": [1.0, 2.0]})
    s = spec(title=evil, summary=f'"{evil}" 입니다.',
             sections=[{"heading": evil, "text": evil, "blocks": [
                 block(type="chart", artifact_id="price_series", x="date", y=["price"], title=evil),
                 block(type="flow", steps=['A"] --> B[<img src=x onerror=alert(1)>']),
                 block(type="callout", text=evil)]}],
             limits=[evil])

    def setup_evil(state, ctx):
        state.plan = {"goal": evil, "output_format": "report", "needs": {}, "notice": evil}
        state.selection = {"selected": [], "excluded": []}
        state.artifacts = {"price_series": art("price_series", "series", df)}
        state.tasks = [{"id": "t1", "title": evil, "status": "ok", "attempts": [], "artifact_ids": ["price_series"]}]
        state.unanswered = [{"what": evil, "why": evil}]
        return state
    stages = [Stage("s1_parse", types.SimpleNamespace(run=setup_evil)), Stage("s5_render", s5_render)]
    res = run_agent(evil, llm=FakeLLM([s]), data=SnapshotRegistry(), runs_dir=tmp_path, stages=stages)
    h = res.html
    assert "<script>alert(1)" not in h and "<img" not in h and "</script><b>" not in h
    # 문서 안의 <script> 여는 태그는 우리가 넣은 것뿐
    assert all(re.match(r'<script( src="https://(cdn.jsdelivr.net|unpkg.com)/[^"]+"| type="application/json" id="d-b\d+")?>', m)
               for m in re.findall(r"<script[^>]*>", h)), re.findall(r"<script[^>]*>", h)


def test_fallback_when_limit_hit_has_no_llm(tmp_path):
    def burn(state, ctx):
        ctx.llm.text("s", "u")
        return state
    def setup(state, ctx):
        state.plan = {"goal": "월동무", "output_format": "report", "needs": {}}
        state.selection = {"selected": [{"dataset_id": DS, "reason": "r", "role": "primary"}], "excluded": []}
        state.artifacts = {"price_series": art("price_series", "series", SERIES)}
        state.tasks = [{"id": "t1", "title": "시계열", "status": "ok", "attempts": [], "artifact_ids": ["price_series"]}]
        ctx.llm.text("s", "u")  # 상한(1회) 초과 호출
        ctx.llm.text("s", "u")
    stages = [Stage("s1_parse", types.SimpleNamespace(run=setup)), Stage("s5_render", s5_render)]
    llm = FakeLLM(["a", "b", spec()])
    res = run_agent("월동무", llm=llm, data=SnapshotRegistry(), runs_dir=tmp_path, stages=stages, limits=Limits(max_llm_calls=1))
    assert res.state.limit_hit == "llm_calls" and res.status == "partial"
    assert len(llm.calls) == 1                                    # 렌더에서 LLM을 다시 부르지 않았다
    assert "<table>" in res.html and "AI 요약 없이" in res.html and "상한" in res.html
    for s in COMMON:
        assert s in res.html


def test_llm_error_falls_back(tmp_path):
    res, _ = go(tmp_path, [LLMError("boom")])
    assert res.status == "answered" and "AI 요약 없이" in res.html and "<table>" in res.html


def test_nothing_to_render_passes_through(tmp_path):
    res, llm = go(tmp_path, [], with_artifacts=False)
    assert res.html is None and llm.calls == []
