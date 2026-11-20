"""티켓 13: 리포트 생성. 작은 가짜 결과로 마크다운 내용을 확인한다."""
import pytest
import report
from test_eval_metrics import q, r


def build(**kw):
    qs = [q("a", needs={"point_analysis": True}, must_include=["D"], must_exclude=["C"]),
          q("b", amb=True), q("c", "infeasible")]
    rs = [r("a", selected=[{"dataset_id": "C", "role": "primary"}], excluded=[{"dataset_id": "D", "reason_code": "irrelevant", "by": "llm"}],
           tasks=[{"id": "t1", "title": "t", "status": "failed", "failure": {"why": "형식이 다르다", "classification": "format_error"},
                   "module": {"decision": "new"}, "attempts": [{"n": 1, "kind": "generate", "ok": False, "failure": "format_error", "phase": "mock"},
                                                              {"n": 2, "kind": "fix_code", "ok": False, "failure": "format_error", "phase": "mock"}]}],
           unanswered=[{"what": "지점", "why": "없다"}]),
          r("b", "failed", message="모든 작업 실패"), r("c", "infeasible")]
    return report.build_report(rs, qs, {"llm": "openai", "model": "gpt-4o", **kw}, crossval=["(cv)"])


def test_markdown_has_all_sections_and_mismatch_detail():
    t = build()
    for h in ("# 평가 리포트", "## 1. 지표", "## 2. 애매한 질문 지표", "## 3. 정답과 다른 질문", "## 4. 실패 분류별 집계",
              "## 5. 비용·시간", "## 6. 지점 기온 교차검증 오차"):
        assert h in t
    assert "드라이런" not in t
    # 불일치 상세: 기대 vs 관측 + trace 요약 (선택/제외, 작업 시도, 미답변)
    assert "#### a [c]" in t and "필요 데이터 누락" in t and "제외할 데이터를 선택함" in t
    assert "format_error" in t and "1회(generate)X:format_error" in t and "미답변: 지점 - 없다" in t
    assert "#### b [c]" in t and "모든 작업 실패" in t        # 애매한 질문도 별도 절에 나온다
    assert t.index("### 3-1") < t.index("#### a [c]") < t.index("### 3-2") < t.index("#### b [c]")


def test_not_applicable_is_written_not_zero():
    t = build()
    row = next(x for x in t.splitlines() if x.startswith("| 해상도 함정 통과율"))
    assert "해당 없음" in row and "0.0%" not in row


def test_dry_run_banner():
    assert "드라이런(가짜 LLM)입니다" in build(dry_run=True)


def test_crossval_uses_collected_weather():
    pytest.importorskip("rasterio")
    from jejuagent.geo import dem
    if not dem._files():
        pytest.skip("DEM 도엽 없음")
    t = "\n".join(report.crossval_markdown())
    assert "jeju_weather_daily" in t and "idw_lapse_fixed" in t and "nearest_station" in t
